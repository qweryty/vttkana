from typing import Optional, List
import webvtt
from webvtt.structures import Style
import pykakasi
import os
from tqdm import tqdm
from janome.tokenizer import Tokenizer
from janome.analyzer import Analyzer
from janome.tokenfilter import CompoundNounFilter, POSKeepFilter, POSStopFilter
from janome.charfilter import UnicodeNormalizeCharFilter, RegexReplaceCharFilter
import csv
import json
import argparse
import re
import datetime
from enum import Enum

STYLE = Style()
STYLE.text = '''
STYLE
::cue(rt) {
    background-color: rgba(0,0,0,.9);
}
'''
RT_REGEX_STRING = r'<rt>.*?</rt>'
RT_REGEX = re.compile(RT_REGEX_STRING)
RUBY_REGEX_STRING = r'</?ruby>'
RUBY_REGEX = re.compile(RUBY_REGEX_STRING)

POS_FILTER = [
    '助詞',  # particle
    '副詞,助詞類接続',  # adverbs, particles conjunction
    '助動詞',  # auxiliary verb
    '名詞,非自立,助動詞語幹',  # noun, non-independent, auxiliary verb stem
    '記号',  # symbol
    '接頭詞', # prefix
    '名詞,接尾',  # noun, suffix
    '動詞,接尾',  # verb, suffix
    '形容詞,接尾',  # adjective, suffix
    '接尾',  # suffix
    '名詞,数',  # noun, number
    '数',  # number
    'フィラー',  # filler
]

class VocabularyType(str, Enum):
    JSON = 'json'
    CSV = 'csv'

def jsonify_vocabulary(vocabulary):
    for value in vocabulary.values():
        if isinstance(value['occurences'], set):
            value['occurences'] = list(value['occurences'])
        else:
            for key, occurences in value['occurences'].items():
                value['occurences'][key] = list(occurences)

def save_vocabulary_csv(vocabulary, filename):
    with open(filename, 'w') as csvfile:
        jsonify_vocabulary(vocabulary)
        writer = csv.writer(csvfile)
        writer.writerows(
            sorted(
                [(key, value['frequency'], json.dumps(value['occurences'])) for key, value in vocabulary.items()], 
                key=lambda item: item[1], reverse=True
            )
        )


def load_vocabulary_csv(filename):
    with open(filename, 'r') as csvfile:
        reader = csv.reader(csvfile)
        vocabulary = {}
        for key, frequency, occurences in reader:
            vocabulary[key] = {
                'frequency': frequency,
                'occurences': json.loads(occurences),
            }

    return vocabulary


def save_vocabulary_json(vocabulary, filename):
    with open(filename, 'w') as json_file: 
        jsonify_vocabulary(vocabulary)
        json.dump(vocabulary, json_file)


def load_vocabulary_json(filename):
    with open(filename, 'r') as json_file: 
        return json.load(json_file)


def filter_node(node):
    for pos in POS_FILTER:
        if node.part_of_speech.startswith(pos):
            return True

    return False


def analyze_subtitles(subtitles, analyzer):
    vocabulary = {}

    for caption in subtitles:
        analyzed = analyzer.analyze(caption.raw_text)
        for a in analyzed:
            if a.extra is not None:
                dict_form = a.extra[3]
            elif hasattr(a.node, 'base_form'):
                if filter_node(a.node):
                    continue
                dict_form = a.node.base_form
            else:
                print(f'No base form for "{a.node.surface}"')
                continue
            if dict_form not in vocabulary:
                vocabulary[dict_form] = {'frequency': 0, 'occurences': set()}
            vocabulary[dict_form]['frequency'] += 1
            vocabulary[dict_form]['occurences'].add(caption.start_in_seconds)

    return vocabulary


def add_furigana_to_subtitles(subtitles, kks):
    for caption in subtitles:
        converted = kks.convert(caption.raw_text)
        converted_string = ''
        for item in converted:
            if item['orig'] == item['hira'] or item['orig'] == item['kana']:
                converted_string += item['orig']
            else:
                converted_string += f'<ruby>{item["orig"]}<rt>{item["hira"]}</rt></ruby>'
        caption.text = converted_string


def convert(
    input_directory: str, 
    output_directory: Optional[str] = None, 
    add_furigana: bool = False, 
    extract_vocabulary: bool = False, 
    single_vocabulary_file: Optional[str] = None,
    vocabulary_type: VocabularyType = VocabularyType.JSON,
    **kwargs
):
    if (add_furigana or (extract_vocabulary and not single_vocabulary_file)) and not output_directory:
        raise Exception('Output directory required when extracting vocabulary or adding furigana')

    kks = pykakasi.Kakasi()
    tokenizer = Tokenizer()
    char_filters = [
        UnicodeNormalizeCharFilter(),
        RegexReplaceCharFilter(RT_REGEX_STRING, ''),
        RegexReplaceCharFilter(RUBY_REGEX_STRING, ''),
        # RegexReplaceCharFilter(r'[a-z,A-Z,\']+', ''),
        RegexReplaceCharFilter(r'!+', '！'),
        RegexReplaceCharFilter(r'\'+', '’'),
        RegexReplaceCharFilter(r'\?+', '？'),
        RegexReplaceCharFilter(r'\.+', '。'),
    ]

    token_filters = [CompoundNounFilter(), POSStopFilter(POS_FILTER)]
    analyzer = Analyzer(char_filters=char_filters, token_filters=token_filters, tokenizer=tokenizer)
    common_vocabulary = {}

    if output_directory is not None and not os.path.exists(output_directory):
        os.mkdir(output_directory)

    for filename in tqdm(os.listdir(input_directory)):
        file_path = os.path.join(input_directory, filename)
        if not os.path.isfile(file_path) or not filename.lower().endswith('.vtt'):
            continue

        subtitles = webvtt.read(file_path)
        # FIXME https://github.com/glut23/webvtt-py/pull/42
        subtitles.styles.append(STYLE)

        if extract_vocabulary:
            vocabulary = analyze_subtitles(subtitles, analyzer)

            base_name = os.path.splitext(filename)[0]
            if not single_vocabulary_file:
                if vocabulary_type == VocabularyType.CSV:
                    save_vocabulary_csv(vocabulary, os.path.join(output_directory, base_name + '.csv'))
                else:
                    save_vocabulary_json(vocabulary, os.path.join(output_directory, base_name + '.json'))
            else:
                for key, value in vocabulary.items():
                    if key not in common_vocabulary:
                        common_vocabulary[key] = {'frequency': 0, 'occurences': {}}

                    common_vocabulary[key]['frequency'] += value['frequency']
                    common_vocabulary[key]['occurences'][base_name] = value['occurences']
        
        if add_furigana:
            add_furigana_to_subtitles(subtitles, kks)
            subtitles.save(os.path.join(output_directory, filename))

    if extract_vocabulary and single_vocabulary_file:
        if vocabulary_type == VocabularyType.CSV:
            save_vocabulary_csv(common_vocabulary, single_vocabulary_file)
        else:
            save_vocabulary_json(common_vocabulary, single_vocabulary_file)

def print_occurences_for_file_path(query: str, timestamps: List[str], file_path: str):
    timestamps.sort()
    subtitles = webvtt.read(file_path)
    current_timestamp = 0
    print(file_path)
    for caption in subtitles:
        if current_timestamp >= len(timestamps):
            break
        if caption.end_in_seconds <= timestamps[current_timestamp]:
            continue

        print(
            f"{datetime.timedelta(seconds=timestamps[current_timestamp])}: "
            f"{RUBY_REGEX.sub('', RT_REGEX.sub('', caption.raw_text))}"
        )
        current_timestamp += 1

def find_examples(
    query: str, 
    vocabulary_file: str, 
    subtitles_directory: Optional[str] = None, 
    subtitles_file: Optional[str] = None, 
    **kwargs
): 
    if not subtitles_directory and not subtitles_file:
        raise Exception('Either the subtitles directory or subtitles file should be specified')

    if(vocabulary_file.endswith('.csv')):
        vocabulary = load_vocabulary_csv(vocabulary_file)
    else:
        vocabulary = load_vocabulary_json(vocabulary_file)

    if query not in vocabulary:
        print(f'{query} was not found in vocabulary file')
        return

    occurences = vocabulary[query]['occurences']
    if isinstance(occurences, list):
        if not subtitles_file:
            raise Exception('vocabulary was generated for a single file which was not specified')

        print_occurences_for_file_path(query, occurences, subtitles_file)
    else:
        if not subtitles_directory:
            raise Exception('vocabulary was generated for a directory which was not specified')

        for filename, timestamps in occurences.items():
            file_path = os.path.join(subtitles_directory, filename + '.vtt')
            print_occurences_for_file_path(query, timestamps, file_path)


if __name__ == '__main__':
    argument_parser = argparse.ArgumentParser()
    subparsers = argument_parser.add_subparsers()

    convert_parser = subparsers.add_parser('convert')
    convert_parser.add_argument('input_directory')
    convert_parser.add_argument('-o', '--output-directory', action='store')
    convert_parser.add_argument(
        '-a', '--add-furigana', action='store_true', help='adds furigana to subtitles'
    )
    convert_parser.add_argument(
        '-e', '--extract-vocabulary', action='store_true', help='extracts vocabulary from subtitle files'
    )
    convert_parser.add_argument(
        '-s', 
        '--single-vocabulary-file', 
        action='store', 
        help='stores extracted vocabulary from all subtitles in single file'
    )
    convert_parser.add_argument(
        '-t', 
        '--vocabulary-type',
        choices=[e.value for e in VocabularyType],
        action='store',
        default=VocabularyType.JSON,
        help='file type for vocabulary'
    )
    convert_parser.set_defaults(func=convert)

    find_examples_parser = subparsers.add_parser('find-examples', help='outputs examples of specified word')
    find_examples_parser.add_argument('query', help='word to be searched in dictionary form')
    find_examples_parser.add_argument('-v', '--vocabulary-file', action='store', required=True)
    find_examples_parser.add_argument('-d', '--subtitles-directory', action='store')
    find_examples_parser.add_argument('-f', '--subtitles-file', action='store')
    find_examples_parser.set_defaults(func=find_examples)

    args = argument_parser.parse_args()
    args.func(**vars(args))

    # main(
    #     input_directory=args.input_directory, 
    #     output_directory=args.output_directory,
    #     add_furigana=args.add_furigana,
    #     extract_vocabulary=args.extract_vocabulary,
    #     single_vocabulary_file=args.single_vocabulary_file,
    #     vocabulary_type=args.vocabulary_type,
    # )