import math
from enum import IntEnum
import matplotlib.pyplot as plt
import numpy as np
import util
import cv2
from abc import *
from scipy.interpolate import interp1d


class GolfEnv(metaclass=ABCMeta):
    IMG_PATH = "resources/env.png"
    IMG_SIZE_X = 500
    IMG_SIZE_Y = 500
    START_X = 256
    START_Y = 116
    PIN_X = 280
    PIN_Y = 430
    STATE_IMAGE_WIDTH = 300
    STATE_IMAGE_HEIGHT = 300
    STATE_IMAGE_OFFSET_HEIGHT = -20
    OUT_OF_IMG_INTENSITY = 0

    class NoAreaInfoAssignedException(Exception):
        def __init__(self, pixel):
            self.pixel = pixel

        def __str__(self):
            return 'Cannot convert given pixel intensity ' + str(self.pixel) + ' to area info.'

    class AreaInfo(IntEnum):
        NAME = 0
        DIST_COEF = 1
        DEV_COEF = 2
        ON_LAND = 3
        TERMINATION = 4
        REWARD = 5

    class OnLandAction(IntEnum):
        NONE = 0
        ROLLBACK = 1
        SHORE = 2

    def __init__(self):
        self.__step_n = 0
        self.__ball_path_x = []
        self.__ball_path_y = []
        self._state = {
            'ball_pos': np.array([0]),
            'distance_to_pin': 0.0,
            'landed_pixel_intensity': 0,
            'state_img': np.array([0])
        }
        self.__img = cv2.cvtColor(cv2.imread(self.IMG_PATH), cv2.COLOR_BGR2RGB)
        self.__img_gray = cv2.cvtColor(cv2.imread(self.IMG_PATH), cv2.COLOR_BGR2GRAY)
        self.__area_info = {
            # PIXL   NAME       K_DIST  K_DEV   ON_LAND TERM                RWRD
            -1: ('TEE', 1.0, 1.0, self.OnLandAction.NONE, False, lambda d: -1),
            70: ('FAREWAY', 1.0, 1.0, self.OnLandAction.NONE, False, lambda d: -1),
            80: ('GREEN', 1.0, 1.0, self.OnLandAction.NONE, True, lambda d: -1 + self.green_reward_func(d)),
            50: ('SAND', 0.6, 1.5, self.OnLandAction.NONE, False, lambda d: -1),
            5: ('WATER', 0.4, 1.0, self.OnLandAction.SHORE, False, lambda d: -2),
            55: ('ROUGH', 0.8, 1.5, self.OnLandAction.NONE, False, lambda d: -1),
            0: ('OB', 1.0, 1.0, self.OnLandAction.ROLLBACK, False, lambda d: -3),
        }
        self.green_reward_func = interp1d(np.array([0, 1, 3, 15, 100]), np.array([-1, -1, -2, -3, -3]))
        self.rng = np.random.default_rng()

        # find fairway regression
        # img_bin = cv2.inRange(self.__img_gray, 70-1, 70+1)
        # whites = np.argwhere(img_bin == 255)
        #
        # fit_param = np.polyfit(whites[:, 0], whites[:, 1], 3)
        #
        # def fit(x):
        #     return x ** 3 * fit_param[0] + x ** 2 * fit_param[1] + x ** 1 * fit_param[2] + fit_param[3]
        #
        # self.fit_f = np.vectorize(fit)

    @abstractmethod
    def _get_flight_model(self, distance_action):
        """
        :param distance_action: scalar of distance action, can be either discrete or continuous depending on
        subclass implementation
        :return: tuple of ball flight model (distance, var_x, var_y)
        """
        pass

    def _generate_debug_str(self, msg):
        return msg

    def reset(self):
        """
        :return: tuple of initial state(img, dist), r:rewards term:termination
        """
        self.__step_n = 0
        self.__ball_path_x = [self.START_X]
        self.__ball_path_y = [self.START_Y]

        # get ball pos, dist_to_pin
        self._state['ball_pos'] = np.array([self.START_X, self.START_Y])
        self._state['distance_to_pin'] = np.linalg.norm(self._state['ball_pos'] - np.array([self.PIN_X, self.PIN_Y]))
        self._state['state_img'] = self.__generate_state_img(self.START_X, self.START_Y)
        self._state['landed_pixel_intensity'] = self.__get_pixel_on([self.START_X, self.START_Y])

        return self._state['state_img'], self._state['distance_to_pin']

    def step(self, action, debug=False):
        """
        steps simulator
        :param action: tuple of action(continuous angle(deg), continuous distance(m))
        :param debug: print debug message of where the ball landed etc.
        :return: tuple of transition (s,r,term)
        s:tuple of state(img, dist), r:rewards term:termination
        """
        self.__step_n += 1

        # get flight model
        area_info = self.__area_info[self._state['landed_pixel_intensity']]
        dist_coef = area_info[self.AreaInfo.DIST_COEF]
        dev_coef = area_info[self.AreaInfo.DEV_COEF]
        distance, dev_x, dev_y = self._get_flight_model(action[1])
        reduced_distance = distance * dist_coef

        # get tf delta of (x,y)
        angle_to_pin = math.atan2(self.PIN_Y - self._state['ball_pos'][1], self.PIN_X - self._state['ball_pos'][0])
        shoot = np.array([[reduced_distance, 0]]) + self.rng.normal(size=2, scale=[dev_x * dev_coef, dev_y * dev_coef])
        delta = np.dot(util.rotation_2d(util.deg_to_rad(action[0]) + angle_to_pin), shoot.transpose()).transpose()

        # offset tf by delta to derive new ball pose
        new_ball_pos = np.array([self._state['ball_pos'][0] + delta[0][0], self._state['ball_pos'][1] + delta[0][1]])

        # store position for plotting
        self.__ball_path_x.append(new_ball_pos[0])
        self.__ball_path_y.append(new_ball_pos[1])

        # get landed pixel intensity, area info
        new_pixel = self.__get_pixel_on(new_ball_pos)
        if new_pixel not in self.__area_info:
            raise GolfEnv.NoAreaInfoAssignedException(new_pixel)
        area_info = self.__area_info[new_pixel]

        # get distance to ball
        distance_to_pin = np.linalg.norm(new_ball_pos - np.array([self.PIN_X, self.PIN_Y]))

        # get reward, termination from reward dict
        reward = area_info[self.AreaInfo.REWARD](distance_to_pin)
        termination = area_info[self.AreaInfo.TERMINATION]

        if area_info[self.AreaInfo.ON_LAND] == self.OnLandAction.NONE:
            # get state img
            state_img = self.__generate_state_img(new_ball_pos[0], new_ball_pos[1])

            # update state
            self._state['state_img'] = state_img
            self._state['distance_to_pin'] = distance_to_pin
            self._state['ball_pos'] = new_ball_pos
            self._state['landed_pixel_intensity'] = new_pixel

        elif area_info[self.AreaInfo.ON_LAND] == self.OnLandAction.ROLLBACK:
            # add previous position to scatter plot to indicate ball return when rolled back
            self.__ball_path_x.append(self._state['ball_pos'][0])
            self.__ball_path_y.append(self._state['ball_pos'][1])

        elif area_info[self.AreaInfo.ON_LAND] == self.OnLandAction.SHORE:
            # get angle to move
            from_pin_vector = np.array([new_ball_pos[0] - self.PIN_X, new_ball_pos[1] - self.PIN_Y]).astype('float64')
            from_pin_vector /= np.linalg.norm(from_pin_vector)

            while True:
                new_ball_pos += from_pin_vector
                print(new_ball_pos)
                if not self.__area_info[self.__get_pixel_on(new_ball_pos)][self.AreaInfo.ON_LAND] == self.OnLandAction.SHORE: break

            # get state img
            state_img = self.__generate_state_img(new_ball_pos[0], new_ball_pos[1])

            # add previous position to scatter plot to indicate ball return when rolled back
            self.__ball_path_x.append(new_ball_pos[0])
            self.__ball_path_y.append(new_ball_pos[1])

            # update state
            self._state['state_img'] = state_img
            self._state['distance_to_pin'] = distance_to_pin
            self._state['ball_pos'] = new_ball_pos
            self._state['landed_pixel_intensity'] = new_pixel

        # print debug
        if debug:
            print('itr' + str(self.__step_n) + ': ' + self._generate_debug_str(
                'landed on ' + area_info[self.AreaInfo.NAME] +
                ' dist_coef:' + str(dist_coef) +
                ' dev_coef:' + str(dev_coef) +
                ' on_land:' + str(area_info[self.AreaInfo.ON_LAND]) +
                ' termination:' + str(termination) +
                ' distance:' + str(self._state['distance_to_pin']) +
                ' reward:' + str(reward)))

        return (self._state['state_img'], self._state['distance_to_pin']), reward, termination

    def plot(self):
        # test_x = np.linspace(0, 400, 1000)
        # test_y = self.fit_f(test_x)

        plt.figure(figsize=(10, 10))
        plt.xlabel('X')
        plt.ylabel('Y')
        plt.xlim([0, self.IMG_SIZE_X])
        plt.ylim([0, self.IMG_SIZE_Y])
        plt.imshow(plt.imread(self.IMG_PATH), extent=[0, self.IMG_SIZE_X, 0, self.IMG_SIZE_Y])
        # plt.plot(test_x, test_y)
        # plt.scatter(self.PIN_X, self.PIN_Y, s=500, marker='x', color='black')
        # plt.scatter(self.START_X, self.START_Y, s=200, color='black')
        plt.plot(self.__ball_path_x, self.__ball_path_y, marker='o', color="white")
        plt.show()

    def show_grayscale(self):
        plt.imshow(cv2.cvtColor(self.__img_gray, cv2.COLOR_GRAY2BGR))
        plt.show()

    def __get_pixel_on(self, ball_pos):
        x0 = int(round(ball_pos[0]))
        y0 = int(round(ball_pos[1]))
        if util.is_within([0, 0], [self.IMG_SIZE_X - 1, self.IMG_SIZE_Y - 1], [x0, y0]):
            return self.__img_gray[-y0 - 1, x0]
        else:
            return self.OUT_OF_IMG_INTENSITY

    def __generate_state_img(self, x, y):
        # get angle
        angle_to_pin = math.atan2(self.PIN_Y - y, self.PIN_X - x)

        # get tf between fixed frame and moving frame (to use p0 = t01*p1)
        t01 = util.transform_2d(x, y, angle_to_pin)

        # generate image
        state_img = np.zeros((self.STATE_IMAGE_HEIGHT, self.STATE_IMAGE_WIDTH), np.uint8)
        state_img_y = 0

        for y in range(self.STATE_IMAGE_OFFSET_HEIGHT, self.STATE_IMAGE_HEIGHT + self.STATE_IMAGE_OFFSET_HEIGHT):
            state_img_x = 0
            for x in range(int(-self.STATE_IMAGE_WIDTH / 2), int(self.STATE_IMAGE_WIDTH / 2)):
                p1 = np.array([[y, x, 1]])
                p0 = np.dot(t01, p1.transpose())
                x0 = int(round(p0[0, 0]))
                y0 = int(round(p0[1, 0]))

                if util.is_within([0, 0], [self.IMG_SIZE_X - 1, self.IMG_SIZE_Y - 1], [x0, y0]):
                    state_img[- state_img_y - 1, - state_img_x - 1] = self.__img_gray[-y0 - 1, x0]
                else:
                    state_img[- state_img_y - 1, - state_img_x - 1] = self.OUT_OF_IMG_INTENSITY

                state_img_x = state_img_x + 1
            state_img_y = state_img_y + 1

        return state_img