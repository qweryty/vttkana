import webvtt
from webvtt.structures import Style
import pykakasi
import os
from tqdm import tqdm

STYLE = Style()
STYLE.text = '''
STYLE
::cue(rt) {
    background-color: rgba(0,0,0,.9);
}
'''

def main():
    input_path = './subtitles'
    output_path = './converted'
    kks = pykakasi.kakasi()

    if not os.path.exists(output_path):
        os.mkdir(output_path)
    for filename in tqdm(os.listdir(input_path)):
        file_path = os.path.join(input_path, filename)
        if not os.path.isfile(file_path) or not filename.lower().endswith('.vtt'):
            continue

        subtitles = webvtt.read(file_path)
        # FIXME https://github.com/glut23/webvtt-py/pull/42
        subtitles.styles.append(STYLE)
        for caption in subtitles:
            converted = kks.convert(caption.raw_text)
            converted_string = ''
            for item in converted:
                if item['orig'] == item['hira'] or item['orig'] == item['kana']:
                    converted_string += item['orig']
                else:
                    converted_string += f'<ruby>{item["orig"]}<rt>{item["hira"]}</rt></ruby>'
            caption.text = converted_string

        subtitles.save(os.path.join(output_path, filename))



if __name__ == '__main__':
    main()