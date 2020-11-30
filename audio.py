import subprocess
import os
from PIL import Image

def video2mp3(file_name):
    outfile_name = file_name.split('.')[0] + '.mp3'
    subprocess.call('ffmpeg -i ' + file_name
        + ' -f mp3 ' + outfile_name, shell=True)
    return outfile_name


def video_add_mp3(file_name, mp3_file):
    outfile_name = file_name.split('.')[0] + '-txt.mp4'
    subprocess.call('ffmpeg -i ' + file_name
        + ' -i ' + mp3_file + ' -strict -2 -f mp4 '
        + outfile_name, shell=True)

if __name__ == '__main__':
    video_path = input("Video with target audio:")
    output_path = input("Video need audio:")
    out_filename = video2mp3(video_path)
    video_add_mp3(output_path, out_filename)