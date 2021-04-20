# -*- coding: utf-8 -*-
"""
Class definition of YOLO_v3 style detection model on image and video
"""

import colorsys
import os
from timeit import default_timer as timer
import math
import numpy as np
from keras import backend as K
from keras.models import load_model
from keras.layers import Input
from PIL import Image, ImageFont, ImageDraw

from yolo3.model import yolo_eval, yolo_body, tiny_yolo_body
from yolo3.utils import letterbox_image
import os
from keras.utils import multi_gpu_model

  



class YOLO(object):
    _defaults = {
        "model_path": 'model_data/yolov3_tiny_face_model.h5',
        "anchors_path": 'model_data/tiny_yolo_anchors.txt',
        "classes_path": 'model_data/face.txt',
        "score" : 0.3,
        "iou" : 0.45,
        "model_image_size" : (416, 416),
        "gpu_num" : 1,
    }

    @classmethod
    def get_defaults(cls, n):
        if n in cls._defaults:
            return cls._defaults[n]
        else:
            return "Unrecognized attribute name '" + n + "'"

    def __init__(self, **kwargs):
        self.__dict__.update(self._defaults) # set up default values
        self.__dict__.update(kwargs) # and update with user overrides
        self.class_names = self._get_class()
        self.anchors = self._get_anchors()
        self.sess = K.get_session()
        self.boxes, self.scores, self.classes = self.generate()

    def _get_class(self):
        classes_path = os.path.expanduser(self.classes_path)
        with open(classes_path) as f:
            class_names = f.readlines()
        class_names = [c.strip() for c in class_names]
        return class_names

    def _get_anchors(self):
        anchors_path = os.path.expanduser(self.anchors_path)
        with open(anchors_path) as f:
            anchors = f.readline()
        anchors = [float(x) for x in anchors.split(',')]
        return np.array(anchors).reshape(-1, 2)

    def generate(self):
        model_path = os.path.expanduser(self.model_path)
        assert model_path.endswith('.h5'), 'Keras model or weights must be a .h5 file.'

        # Load model, or construct model and load weights.
        num_anchors = len(self.anchors)
        num_classes = len(self.class_names)
        is_tiny_version = num_anchors==6 # default setting
        try:
            self.yolo_model = load_model(model_path, compile=False)
        except:
            self.yolo_model = tiny_yolo_body(Input(shape=(None,None,3)), num_anchors//2, num_classes) \
                if is_tiny_version else yolo_body(Input(shape=(None,None,3)), num_anchors//3, num_classes)
            self.yolo_model.load_weights(self.model_path) # make sure model, anchors and classes match
        else:
            assert self.yolo_model.layers[-1].output_shape[-1] == \
                num_anchors/len(self.yolo_model.output) * (num_classes + 5), \
                'Mismatch between model and given anchor and class sizes'

        print('{} model, anchors, and classes loaded.'.format(model_path))

        # Generate colors for drawing bounding boxes.
        hsv_tuples = [(x / len(self.class_names), 1., 1.)
                      for x in range(len(self.class_names))]
        self.colors = list(map(lambda x: colorsys.hsv_to_rgb(*x), hsv_tuples))
        self.colors = list(
            map(lambda x: (int(x[0] * 255), int(x[1] * 255), int(x[2] * 255)),
                self.colors))
        np.random.seed(10101)  # Fixed seed for consistent colors across runs.
        np.random.shuffle(self.colors)  # Shuffle colors to decorrelate adjacent classes.
        np.random.seed(None)  # Reset seed to default.

        # Generate output tensor targets for filtered bounding boxes.
        self.input_image_shape = K.placeholder(shape=(2, ))
        if self.gpu_num>=2:
            self.yolo_model = multi_gpu_model(self.yolo_model, gpus=self.gpu_num)
        boxes, scores, classes = yolo_eval(self.yolo_model.output, self.anchors,
                len(self.class_names), self.input_image_shape,
                score_threshold=self.score, iou_threshold=self.iou)
        return boxes, scores, classes

    def detect_image(self, image):
        start = timer()

        if self.model_image_size != (None, None):
            assert self.model_image_size[0]%32 == 0, 'Multiples of 32 required'
            assert self.model_image_size[1]%32 == 0, 'Multiples of 32 required'
            boxed_image = letterbox_image(image, tuple(reversed(self.model_image_size)))
        else:
            new_image_size = (image.width - (image.width % 32),
                              image.height - (image.height % 32))
            boxed_image = letterbox_image(image, new_image_size)
        image_data = np.array(boxed_image, dtype='float32')

        print(image_data.shape)
        image_data /= 255.
        image_data = np.expand_dims(image_data, 0)  # Add batch dimension.

        out_boxes, out_scores, out_classes = self.sess.run(
            [self.boxes, self.scores, self.classes],
            feed_dict={
                self.yolo_model.input: image_data,
                self.input_image_shape: [image.size[1], image.size[0]],
                K.learning_phase(): 0
            })

        print('Found {} boxes for {}'.format(len(out_boxes), 'img'))

        font = ImageFont.truetype(font='font/FiraMono-Medium.otf',
                    size=np.floor(3e-2 * image.size[1] + 0.5).astype('int32'))
        thickness = (image.size[0] + image.size[1]) // 300

        for i, c in reversed(list(enumerate(out_classes))):
            predicted_class = self.class_names[c]
            box = out_boxes[i]
            score = out_scores[i]

            label = '{} {:.2f}'.format(predicted_class, score)
            draw = ImageDraw.Draw(image)
            label_size = draw.textsize(label, font)

            top, left, bottom, right = box
            top = max(0, np.floor(top + 0.5).astype('int32'))
            left = max(0, np.floor(left + 0.5).astype('int32'))
            bottom = min(image.size[1], np.floor(bottom + 0.5).astype('int32'))
            right = min(image.size[0], np.floor(right + 0.5).astype('int32'))
            print(label, (left, top), (right, bottom))

            if top - label_size[1] >= 0:
                text_origin = np.array([left, top - label_size[1]])
            else:
                text_origin = np.array([left, top + 1])

            # My kingdom for a good redistributable image drawing library.
            ##image = np.asarray(image)
            ##image.flags['WRITEABLE'] = True
            ##mosaic part,CORE------------------&&&&&&&&&&&&&&------
            bounds = (left, top, right, bottom)
            image = image.filter(MyGaussianBlur(radius=29, bounds=bounds))
            ##guassianBlur(image, left, top, right, bottom, 50, 5, 1.5)
            ##---------------&&&&&&&&&&&&&&-------------------------
            ##image = Image.fromarray(image)
            for i in range(thickness):
                draw.rectangle(
                    [left + i, top + i, right - i, bottom - i],
                    outline=self.colors[c])
            draw.rectangle(
                [tuple(text_origin), tuple(text_origin + label_size)],
                fill=self.colors[c])
            draw.text(text_origin, label, fill=(0, 0, 0), font=font)
            del draw

        end = timer()
        print(end - start)
        
        return image

    def close_session(self):
        self.sess.close()

def detect_video(yolo, video_path, output_path=""):
    import cv2
    vid = cv2.VideoCapture(video_path)
    if not vid.isOpened():
        raise IOError("Couldn't open webcam or video")
    video_FourCC    = int(vid.get(cv2.CAP_PROP_FOURCC))
    video_fps       = vid.get(cv2.CAP_PROP_FPS)
    video_size      = (int(vid.get(cv2.CAP_PROP_FRAME_WIDTH)),
                        int(vid.get(cv2.CAP_PROP_FRAME_HEIGHT)))
    isOutput = True if output_path != "" else False
    if isOutput:
        print("!!! TYPE:", type(output_path), type(video_FourCC), type(video_fps), type(video_size))
        out = cv2.VideoWriter(output_path, video_FourCC, video_fps, video_size)
    accum_time = 0
    curr_fps = 0
    fps = "FPS: ??"
    prev_time = timer()
    while True:
        return_value, frame = vid.read()
        if frame is None:
            break
        image = Image.fromarray(frame)
        image = yolo.detect_image(image)
        result = np.asarray(image)
        curr_time = timer()
        exec_time = curr_time - prev_time
        prev_time = curr_time
        accum_time = accum_time + exec_time
        curr_fps = curr_fps + 1
        if accum_time > 1:
            accum_time = accum_time - 1
            fps = "FPS: " + str(curr_fps)
            curr_fps = 0
        cv2.putText(result, text=fps, org=(3, 15), fontFace=cv2.FONT_HERSHEY_SIMPLEX,
                    fontScale=0.50, color=(255, 0, 0), thickness=2)
        cv2.namedWindow("result", cv2.WINDOW_NORMAL)
        cv2.imshow("result", result)
        if isOutput:
            out.write(result)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break
    yolo.close_session()

def mosaic(img, start_y, start_x, end_y, end_x, division):
    rangem = int (min(end_x - start_x, end_y - start_y)/division)
    pallette_h = int((end_x - start_x)/rangem + ((end_x - start_x) % rangem != 0))
    pallette_w = int((end_y - start_y)/rangem + ((end_y - start_y) % rangem != 0))
    pallette = []
    for row in range(0, pallette_h):
        row_pallette = []
        for col in range(0, pallette_w):
            color = [0,0,0]
            for x in range(start_x + row * rangem, min(start_x + (row + 1) * rangem, end_x)):
                for y in range(start_y + col * rangem, min(start_y + (col + 1) * rangem, end_y)):
                    for i in range(0,3):
                        color[i] += img[x][y][i]
            for i in range(0,3):
                color[i] = int(color[i]/((min(start_x + (row + 1) * rangem, end_x) -
                    (start_x + row * rangem)) * (min(start_y + (col + 1) *
                    rangem, end_y) - (start_y + col * rangem))))
            row_pallette.append(color)
        pallette.append(row_pallette)
    for row in range(start_x,end_x):
        for col in range(start_y,end_y):
            for i in range(0,3):
                img[row][col][i] = pallette[int((row - start_x)/rangem)][int((col - start_y)/rangem)][i]


def two_d_guassian_G(x,y,c):
    pi = 3.1415926
    result_G = float(math.exp(-(x**2+y**2)/(2*c**2))/(2*pi*c**2))
    result_G = round(result_G,7)
    return result_G

##method1
def guassianBlur(img, start_y, start_x, end_y, end_x, division, radius, c):
    #Guassian Blur: radius means the blurring radius , c means the value of sigema
    #division is to divide the target area into small pixel squares.
    #---------------------------------------------------------------------
    #the edge of each pixel:
    rangem = int (min(end_x - start_x, end_y - start_y)/division)
    #num of pixels in row:
    pallette_h = int((end_x - start_x)/rangem + ((end_x - start_x) % rangem != 0))
    #num of pixels in col:
    pallette_w = int((end_y - start_y)/rangem + ((end_y - start_y) % rangem != 0))
     #---------------------------------------------------------------------
    #Set an initial 2d array weight matrix with a scale of 2radius * 2radius
    g = [[0 for i in range(2*radius)] for j in range(2*radius)]
    #Start tracing and calculating:
    for row in range(0, pallette_h):
        for col in range(0, pallette_w):
            for x in range(start_x + row * rangem, min(start_x + (row + 1) * rangem, end_x)):
                for y in range(start_y + col * rangem, min(start_y + (col + 1) * rangem, end_y)):
                    for i in range(0,3): # 3 is due to that RGB are three different channels
                      color = [0,0,0]
                      g_total = 0
                      # if on edges, no blurring.
                      if row==0 or col ==0:
                            color[i]=img[x][y][i]
                      else:
                        # if row/col <= radius, the new radius should be the min of them:
                        if row <= radius or col <= radius:
                            radius = min(row,col)
                            
                        # Compute each pixel's gassian percentage:
                        for j in range (0,radius*2):
                            for k in range (0,radius*2):
                                g[j][k] = two_d_guassian_G(j-radius,k-radius,c)
                                ## compute the sum of all g_weight
                                g_total += g[j][k]
                                
                        #--------------------------------------------
                        for j in range (0,radius*2):
                            for k in range (0,radius*2):
                                #compute the weighted sum of each R,G,B
                                color[i] += (img[x+(row+j-radius)*rangem][y+(col+k-radius)*rangem][i])*(g[j][k]/g_total)
                         #End Guassian blur, assign light values to this central pixel.
                      img[row][col][i] = color[i]
                   


##method 2
from PIL import Image, ImageFilter

class MyGaussianBlur(ImageFilter.Filter):
  name = "GaussianBlur"

  def __init__(self, radius=2, bounds=None):
    self.radius = radius
    self.bounds = bounds

  def filter(self, image):
    if self.bounds:
      clips = image.crop(self.bounds).gaussian_blur(self.radius)
      image.paste(clips, self.bounds)
      return image
    else:
      return image.gaussian_blur(self.radius)
      
def guassianBlur2(img, start_y, start_x, end_y, end_x, division):
    bounds = (start_x, end_x, start_y, end_y)
  
    image = image.filter(MyGaussianBlur(radius=29, bounds=bounds))
    
    ##: link tohttps://blog.csdn.net/gangtieren/article/details/98870639
