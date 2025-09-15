import os
import time
import threading
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import subprocess
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders


file_total_amount = 30 * 1024**3 #30GB 기준. 30GB가 넘어가면 자동으로 30% 이상 오래된 파일들을 순서로 삭제
saved_videos_list = []
danger = 'danger_videos'
normal = 'normal_videos'
thumbnail = 'thumbnails'
total = 0

list_lock = threading.Lock() #파일 용량 측정 혹은 삭제 중 새로운 파일들이 들어오면 생길 수 있는 오류 방지



# --- 이메일 설정 ---
SENDER_EMAIL = 'EMAIL_SENDER'  # 보내는 사람 이메일 주소
SENDER_PASSWORD = 'APP_PASSWORD'      # Gmail 앱 비밀번호
RECIPIENT_EMAIL = 'EMAIL_RECEIVER' # 받는 사람 이메일 주소
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587 

# --- 썸네일 파일과 함께 이메일을 전송한 후 성공하면 자동으로 썸네일 파일 삭제 ---
def send_email_with_attachment(recipient, subject, body, attachment_path):
    try:
        # 메시지 생성
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = recipient
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        # 첨부 파일 추가
        filename = os.path.basename(attachment_path)
        with open(attachment_path, 'rb') as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
        encoders.encode_base64(part)
        part.add_header(
            'Content-Disposition',
            f'attachment; filename= {filename}',
        )
        msg.attach(part)

        # SMTP 서버 연결 및 이메일 발송
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, recipient, msg.as_string())
        
        print(f"[알림] 이메일 발송 성공: '{filename}' 첨부 완료")

        # 이메일 발송 성공 시 썸네일 파일 삭제
        os.remove(attachment_path)
        print(f"[알림] 썸네일 파일 삭제 완료: {attachment_path}")
        
        return True

    except Exception as e:
        print(f"[경고] 이메일 발송 실패: {e}")
        return False

# --- 파일 감지 핸들러 ---
class ThumbnailHandler(FileSystemEventHandler):
    def on_created(self, event):
        # 디렉토리가 아니고, 이미지 파일인 경우에만 처리
        if not event.is_directory and event.src_path.endswith(('.jpg', '.jpeg', '.png')):
            print(f'[!] 썸네일 파일 생성 감지: {event.src_path}')
            
            time.sleep(0.25) 
            
            # 이메일 내용 설정
            subject = 'CCTV 위험 상황 감지 알림'
            body = f'새로운 위험 상황이 감지되었습니다. 썸네일 파일을 확인하세요: {os.path.basename(event.src_path)}'
            
            # 이메일 발송 함수 호출
            send_email_with_attachment(RECIPIENT_EMAIL, subject, body, event.src_path)


#rclone을 사용하여 사용자의 클라우드 혹은 드라이브와 연동
def rclone_sync(source_path, dest_path):
    print(f'[Notice] Rclone Sync Start {source_path}->{dest_path}')
    try:
        result = subprocess.run(['rclone', 'copy', source_path, dest_path], check = True, capture_output = True, text = True)
        print('[Info] Rclone sync success')
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print(f'[Warning] Rclone sync failed. {e.stderr}')
    except FileNotFoundError:
        print('f[Warning] Rclone syncs failed Check the files')


#최초 실행시 현재까지 분류된 영상 파일들의 총 용량을 계산
def get_current_video_size():
    global total, saved_videos_list
    with list_lock:
        print('현재 총 용량 파악 중..')
        for i in [danger, normal]:
            for file_name in os.listdir(i):
                file_path = os.path.join(i, file_name)
                if os.path.isfile(file_path) and file_path.endswith('.avi'):
                    try:
                        file_size = os.path.getsize(file_path)
                        made_time = os.path.getatime(file_path)
                        saved_videos_list.append((file_path,file_size, made_time))
                        total += file_size
                    except (FileNotFoundError, OSError) as e:
                        print(f'{e}')
        saved_videos_list.sort(key = lambda x : x[2])
        print(f'계산 완료. 현재 총 용량 : {total / 1024**3:.2f}GB, 파일 개수 : {len(saved_videos_list)}')

               
#분류된 영상 파일이 들어오면 전체 용량에 추가
def add_to_list(video_path):
    global total, saved_videos_list
    with list_lock:
        try:
            file_size = os.path.getsize(video_path)
            made_time = os.path.getatime(video_path)
            saved_videos_list.append((video_path, file_size, made_time))
            total += file_size
            saved_videos_list.sort(key = lambda x : x[2])
        except (FileNotFoundError, OSError) as e:
            print(f'{e}')

#전체 용량 확인 후 자동 삭제
def check_all_amount_and_delete():
    global saved_videos_list, total
    print('총 저장된 영상 용량 확인 중..')
    print(f'현재 총 용량 : {total/1024**3:.2f}GB')
    with list_lock:
        if (total >= file_total_amount):
            print('자동 삭제를 시작합니다..')
            while(total > file_total_amount*0.7):
                file_path, file_size, _ = saved_videos_list[0]
                try:
                    os.remove(file_path)
                    total -= file_size
                    saved_videos_list.pop(0)
                except (FileNotFoundError, PermissionError, OSError) as e:
                    print(f"{e}")
                    total -= file_size
            print(f'자동 삭제 완료. 현재 총 파일 용량 : {total/1024**3:.2f} GB')
        else:
            print('자동 삭제 미실시.')

# --- 파일 감지 핸들러 ---
class VideoHandler(FileSystemEventHandler):
    def on_moved(self, event):
        if not event.is_directory and event.dest_path.endswith('.avi'):
            print(f'[!] 파일 이동 감지: {event.dest_path}')
            self.wait_for_file_completion(event.dest_path)
            dest_remote = 'cctv:' + os.path.basename(os.path.dirname(event.dest_path))
            rclone_sync(event.dest_path, dest_remote)
            add_to_list(event.dest_path)
            check_all_amount_and_delete()
        else:
            print('[DEBUG-EVENT] on_moved: .avi 파일이 아니거나 디렉토리 이벤트입니다. 스킵.')

    def on_created(self, event):
        if not event.is_directory and event.src_path.endswith('.avi'):
            print(f"[!] 새 파일 생성 감지: {event.src_path}")
            self.wait_for_file_completion(event.src_path)
            dest_remote = "cctv:" + os.path.basename(os.path.dirname(event.src_path))
            rclone_sync(event.src_path, dest_remote)
            add_to_list(event.src_path)
            check_all_amount_and_delete()
        else:
            print('[DEBUG-EVENT] on_created: .avi 파일이 아니거나 디렉토리 이벤트입니다. 스킵.')

    def wait_for_file_completion(self, file_path, timeout=30, check_interval=0.5):
        start_time = time.time()
        last_size = -1
        print(f"[정보] 파일 '{os.path.basename(file_path)}' 쓰기 완료 대기 중...")

        while time.time() - start_time < timeout:
            if not os.path.exists(file_path):
                print(f'[경고] 대기 중 파일이 사라짐: {file_path}')
                return False # 파일이 없어졌다면 중단

            current_size = os.path.getsize(file_path)

            # 파일 크기가 동일하고 0이 아닐 때 (즉, 쓰기가 멈췄을 때)
            if current_size == last_size and current_size > 0:
                print(f"[정보] 파일 '{os.path.basename(file_path)}' 쓰기 완료 감지. 크기: {current_size/1024**3:.2f} GB")
                return True

            last_size = current_size
            time.sleep(check_interval)

        print(f"[경고] 파일 '{os.path.basename(file_path)}' 쓰기 완료 시간 초과. (최종 크기: {last_size} bytes)")
        return False


if __name__ == "__main__":
    get_current_video_size()
    print('대기 중...')

    observer = Observer()
    

    video_handler = VideoHandler()
    observer.schedule(video_handler, danger, recursive=False)
    observer.schedule(video_handler, normal, recursive=False)

    thumbnail_handler = ThumbnailHandler()
    observer.schedule(thumbnail_handler, thumbnail, recursive=False)
    
    observer.start()

    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
