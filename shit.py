import os
import cv2
import time
import json
import numpy as np
from tqdm import tqdm
from skimage.metrics import structural_similarity as ssim
from concurrent.futures import ThreadPoolExecutor
from fpdf import FPDF

# 自实现进度条
def progress_bar(current, total, num_effect_iters ,start_time, prefix=''):
    progress = current / total
    num_blocks = int(progress * 40)
    
    current_time = time.time()
    elapsed_time = current_time - start_time
    if elapsed_time == 0:
        return
    remaining_time = (total - current) / (current / elapsed_time)
    
    elapsed_time_str = time.strftime("%H:%M:%S", time.gmtime(elapsed_time))
    remaining_time_str = time.strftime("%H:%M:%S", time.gmtime(remaining_time))
    
    print('\r', end='', flush=True)
    print(f"{prefix}: [{'#' * num_blocks}{' ' * (40 - num_blocks)}] {current}:{total} {progress:.2%} frame:{num_effect_iters} Elapsed: {elapsed_time_str} etc: {remaining_time_str}", end='', flush=True)

def extract_frames(video_path, output_folder, similarity_threshold, skip_time_ranges=None):
    # Open the video file
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("Error opening video file")
        return
    
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = int(cap.get(cv2.CAP_PROP_FPS)) * 5 
    
    # Create output folder if not exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    frame_list = []
    jump_threshold = fps*2
    init_jump = fps
    jump = init_jump
    
    progress_prefix = f"Processing {os.path.basename(video_path)}"
    start_time = time.time()
    
    i = 1
    while i + jump < frame_count :
        
        # 更新进度条
        progress_bar(current=i, 
                     total=frame_count,
                     prefix=progress_prefix,
                     num_effect_iters = len(frame_list),
                     start_time=start_time
                     )
        
        # 帧处理程序
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = cap.read()
        if not ret:
            break

        # Check if skip_time_ranges is specified and if the current frame falls within any of the ranges
        if skip_time_ranges:
            skip_frame = False
            for skip_range in skip_time_ranges:
                start_time_ms = sum(x * int(t) for x, t in zip([3600000, 60000, 1000], skip_range[0].split(":")))
                end_time_ms = sum(x * int(t) for x, t in zip([3600000, 60000, 1000], skip_range[1].split(":")))
                if start_time_ms <= cap.get(cv2.CAP_PROP_POS_MSEC) <= end_time_ms:
                    skip_frame = True
                    break
            if skip_frame:
                i += fps
                continue
        
        # 抓取后继帧判断稳定性，只对稳定帧进行处理
        cap.set(cv2.CAP_PROP_POS_FRAMES, i+fps)
        ret, next_frame = cap.read()
        if not ret:
            break
        
        next_frame_binary = cv2.adaptiveThreshold(cv2.cvtColor(next_frame, cv2.COLOR_BGR2GRAY), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 11, 2)
        current_frame_binary = cv2.adaptiveThreshold(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 11, 2)
        
        stablity_similarity = ssim(next_frame_binary, current_frame_binary)
        if stablity_similarity > similarity_threshold:
            frame_list.append(frame)
            #combined_image = np.hstack((cv2.resize(current_frame_binary, (0, 0), fx=0.5, fy=0.5), cv2.resize(next_frame_binary, (0, 0), fx=0.5, fy=0.5)))
            #cv2.imshow('Combined Image', combined_image)
            #cv2.waitKey(1)
        else:
            i += fps
            continue
        
        current_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        # Jump sampling
        farthest_similar_frame_index = i
        jump = init_jump
        while i + jump <= frame_count:
            next_frame_index = min(i + jump, frame_count - 1)
            cap.set(cv2.CAP_PROP_POS_FRAMES, next_frame_index)
            ret, next_frame = cap.read()
            if not ret:
                break
            next_frame_gray = cv2.cvtColor(next_frame, cv2.COLOR_BGR2GRAY)
            similarity_next = ssim(current_frame, next_frame_gray)
            if similarity_next <= similarity_threshold:
                # Found a different frame
                if jump > jump_threshold:
                    # Jumped too far, return to previous similar frame
                    i = farthest_similar_frame_index
                    jump = init_jump
                    continue
                else:
                    i = next_frame_index
                    break
            else:
                # No different frame found, continue to next jump
                farthest_similar_frame_index = next_frame_index
            jump *= 2
        
    print("") 
    cap.release()
    if frame_list:
        print('start saving pdf')
        save_frames_as_pdf(frame_list, output_folder, os.path.basename(video_path))


def save_frames_as_pdf(frame_list, output_folder, pdf_name):
    pdf_path = os.path.join(output_folder, pdf_name + ".pdf")
    
    size = (int(1920 // 3.7795), int(1080 // 3.7795))
    pdf = FPDF('P', 'mm', size)

    with tqdm(total=len(frame_list), desc='Converting frames to PDF', unit='frame') as pbar:
        for index, frame in enumerate(frame_list):
            # 将帧转换为图像
            image = frame

            # 将图像保存为临时文件
            temp_image_path = f"{output_folder}/temp_{index}.jpg"
            cv2.imwrite(temp_image_path, image)
            
            pdf.add_page()
            # 将图像添加到PDF页面中
            pdf.image(temp_image_path, 0, 0, size[0], size[1])
            
            os.remove(temp_image_path)
            
            pbar.update(1)
            
    pdf.output(pdf_path, "F")
    print(f"PDF created: {pdf_path}")

def process_videos_asyn(folder_path, video_info_list, similarity_threshold):
    with ThreadPoolExecutor() as executor:
        for video_info in video_info_list:
            video_files = [f for f in os.listdir(folder_path) if f.startswith(video_info['prefix']) and f.endswith('.mp4')]
            for video_file in video_files:
                video_path = os.path.join(folder_path, video_file)
                executor.submit(extract_frames, video_path, folder_path, similarity_threshold, video_info.get('skip_time_ranges'))

def process_videos(folder_path, video_info_list, similarity_threshold):
    for video_info in video_info_list:
        video_files = [f for f in os.listdir(folder_path) if f.startswith(video_info['prefix']) and f.endswith('.mp4')]
        for video_file in video_files:
            video_path = os.path.join(folder_path, video_file)
            extract_frames(video_path, folder_path, similarity_threshold, video_info.get('skip_time_ranges'))

if __name__ == "__main__":
    '''
    视频文件夹:folder_path
    视频信息列表:video_info_list，每个元素是一个字典，包含以下键：
        - 'prefix': 文件名前缀
        - 'skip_time_ranges': 要忽略的时间范围列表，每个元素是一个包含开始和结束时间的元组，如 [('00:01:00', '00:02:30')]
    相似度阈值:similarity_threshold
    '''
    folder_path = "video" 

    with open('video.json', 'r') as f:
        video_info_list = json.load(f)
    similarity_threshold = 0.88  # Adjust the similarity threshold as needed
    
    process_videos(folder_path, video_info_list, similarity_threshold)
