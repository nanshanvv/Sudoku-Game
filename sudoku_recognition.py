# sudoku_recognition.py

import torch
from model import CNN
import numpy as np
import cv2

class NotFoundException(Exception):
    def __init__(self, message="Sudoku Puzzle Not Found"):
        self.message = message
        super().__init__(self.message)

class SudokuRecognition(object):
    device = (
        "cuda"
        if torch.cuda.is_available()
        else "mps"
        if torch.backends.mps.is_available()
        else "cpu"
    )
    model = CNN().to(device)

    @staticmethod
    def sort_contours(cnts, method="left-to-right"):
        reverse=False
        i = 0
        if method == "right-to-left" or method == "bottom-to-top":
            reverse = True
        if method == "top-to-bottom" or method == "bottom-to-top":
            i = 1
        boundingBoxes = [cv2.boundingRect(c) for c in cnts]
        (cnts, boundingBoxes) = zip(*sorted(zip(cnts, boundingBoxes),
            key=lambda b:b[1][i], reverse=reverse))
        return (cnts, boundingBoxes)

    @staticmethod
    def localize_puzzle(im):
        imgray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
        thresh = cv2.adaptiveThreshold(imgray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,57,5)

        cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnt = max(cnts, key=cv2.contourArea)
        
        x, y, w, h = cv2.boundingRect(cnt)

        # Crop and resize
        im = im[y:y+h, x:x+w, :]
        im = cv2.resize(im, (600, 600), interpolation = cv2.INTER_AREA)
        thresh = thresh[y:y+h, x:x+w]
        thresh = cv2.resize(thresh, (600, 600), interpolation = cv2.INTER_AREA)

        
        # Find puzzle in resized image
        cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        cnt = max(cnts, key=cv2.contourArea)

        # Create mask
        mask = np.zeros_like(thresh, dtype=np.uint8)
        cv2.drawContours(mask, [cnt], -1, (255, 255, 255), -1)

        return [im, thresh, mask]


    @staticmethod
    def remove_digits(thresh):
        # Find all contours
        cnts, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        # Filter to get the digit contours
        cnts = [i for i in cnts if cv2.contourArea(i) < 1000]
        
        # "Remove" the digit contours
        cv2.drawContours(thresh, cnts, -1, (0, 0, 0), -1)

        return thresh

    @staticmethod
    def repair_gridlines(thresh, v_iterations, h_iterations):
        vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1,5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, vertical_kernel, iterations=v_iterations)
        horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5,1))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, horizontal_kernel, iterations=h_iterations)

        return thresh

    @staticmethod
    def find_squares(thresh, mask):
        mask = 255 - mask
        thresh = cv2.bitwise_or(thresh,mask)
        thresh = 255 - thresh


        cnts, _ = cv2.findContours(thresh, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)


        # To filter out the noises
        cnts = [i for i in cnts if cv2.contourArea(i) > 100]
        
        if (len(cnts) != 81):
            raise NotFoundException()

        cnts, _ = SudokuRecognition.sort_contours(cnts, 'top-to-bottom')
        
        sudoku = []
        for i in range(9):
            row, _ = SudokuRecognition.sort_contours(cnts[i*9: (i+1)*9])
            sudoku.append(row)

        return sudoku

    @staticmethod
    def recognize_digit(im, cnt):
        # Convert to gray scale
        imgray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)

        # Apply adaptive threshoding
        thresh = cv2.adaptiveThreshold(imgray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV,57,5)
 
        # Create mask
        mask = np.zeros_like(thresh, dtype=np.uint8)

        # Draw mask
        cv2.drawContours(mask, [cnt], -1, (255, 255, 255), -1)

        # Get masked region from the threshold
        thresh = cv2.bitwise_and(thresh, thresh, mask=mask)

        # Remove noises

        kernel = np.ones((2,2),np.uint8)

        thresh = cv2.morphologyEx(thresh, cv2.MORPH_ERODE, kernel)

        # Crop image
        x, y, w, h = cv2.boundingRect(cnt)

        digit = thresh[y:y+h, x:x+w]

        cnts, _ = cv2.findContours(digit, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)

        cnts = [i for i in cnts if cv2.contourArea(i) > 10]

        if (len(cnts) == 0):
            return 0

        digit = cv2.resize(digit, (28, 28), interpolation = cv2.INTER_AREA)
        digit = torch.from_numpy(digit).float().to(SudokuRecognition.device)

        digit /= 255

        digit = digit[None, None, :, :]

        SudokuRecognition.model.load_state_dict(torch.load('./model', map_location='cpu'))

        SudokuRecognition.model.eval()
        pred = SudokuRecognition.model(digit)

        return torch.argmax(pred[0]).item()
    
    @staticmethod
    def recognize_helper(im, v_iterations, h_iterations):
        im, thresh, mask = SudokuRecognition.localize_puzzle(im)
        thresh = SudokuRecognition.remove_digits(thresh)
        thresh = SudokuRecognition.repair_gridlines(thresh, v_iterations, h_iterations)
        squares = SudokuRecognition.find_squares(thresh, mask)
        sudoku = []
        for i in range(9):
            sudoku.append([SudokuRecognition.recognize_digit(im, cnt) for cnt in squares[i]])


        return sudoku

    @staticmethod
    def recognize(im):
        sudoku = None
        for v_iterations in range(1, 20):
            for h_iterations in range(1, 20):
                for alpha in [0, 0.5, 1.0, 1.3, 1.5, 1.7, 2.0]:
                    try:
                        im_copy = np.copy(im)
                        im_copy = cv2.convertScaleAbs(im_copy, alpha=alpha)
                        sudoku = SudokuRecognition.recognize_helper(im_copy, v_iterations, h_iterations)
                        print(sudoku)
                        return sudoku
                    except:
                        continue
        
        return sudoku
