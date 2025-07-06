import customtkinter as ctk
from PIL import Image, ImageTk
import cv2
from pyzbar.pyzbar import decode
import mss
import threading
import time
from tkinter import filedialog

class QRCodeScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("全能二维码扫描器")
        self.geometry("800x600")

        # Main frame
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(padx=10, pady=10, fill="both", expand=True)

        # Video/Image display
        self.image_label = ctk.CTkLabel(self.main_frame, text="图像显示区域\n\n欢迎使用！请从下方选择一个功能。", justify="center")
        self.image_label.pack(pady=10, padx=10, fill="both", expand=True)

        # Result display
        self.result_text = ctk.CTkTextbox(self.main_frame, height=100)
        self.result_text.pack(pady=10, padx=10, fill="x")

        # Button frame
        self.button_frame = ctk.CTkFrame(self)
        self.button_frame.pack(pady=10, padx=10, fill="x")

        self.camera_button = ctk.CTkButton(self.button_frame, text="摄像头实时扫描", command=self.start_camera_scan)
        self.camera_button.pack(side="left", expand=True, padx=5)

        self.upload_button = ctk.CTkButton(self.button_frame, text="上传图片扫描", command=self.upload_image_scan)
        self.upload_button.pack(side="left", expand=True, padx=5)

        self.screen_button = ctk.CTkButton(self.button_frame, text="选区截屏扫描", command=self.screen_shot_scan)
        self.screen_button.pack(side="left", expand=True, padx=5)

        self.realtime_screen_button = ctk.CTkButton(self.button_frame, text="实时区域扫描", command=self.start_realtime_screen_scan)
        self.realtime_screen_button.pack(side="left", expand=True, padx=5)
        
        self.clear_button = ctk.CTkButton(self.button_frame, text="清空 / 返回", command=self.clear_interface, state="disabled")
        self.clear_button.pack(side="left", expand=True, padx=5)

        # Scanning state
        self.scanning = False
        self.scan_thread = None
        self.overlay_window = None

    def start_camera_scan(self):
        self.clear_interface(is_starting_new_task=True)
        self.update_result_text("正在启动摄像头...")
        self.scanning = True
        self.clear_button.configure(state="normal")

        self.scan_thread = threading.Thread(target=self._camera_scan_loop, daemon=True)
        self.scan_thread.start()

    def _camera_scan_loop(self):
        cap = None
        try:
            cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)
            if not cap.isOpened():
                self.after(0, self.update_result_text, "未检测到摄像头，或摄像头正被其他程序占用。")
                self.after(0, self.clear_button.configure, {"state": "normal"})
                self.scanning = False
                return

            while self.scanning:
                ret, frame = cap.read()
                if not ret:
                    self.after(0, self.update_result_text, "无法从摄像头捕获画面。")
                    break

                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)

                self.display_image(pil_image)
                self.decode_and_display(pil_image, "camera")
                
                time.sleep(0.05)

        except Exception as e:
            self.after(0, self.update_result_text, f"摄像头出错: {e}")
        finally:
            if cap:
                cap.release()
            
            self.scanning = False
            self.after(0, self.clear_button.configure, {"state": "normal"})

    def upload_image_scan(self):
        self.clear_interface(is_starting_new_task=True)
        
        file_path = filedialog.askopenfilename(
            title="选择一个二维码图片",
            filetypes=(("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"), ("All files", "*.*" ))
        )
        if not file_path:
            self.clear_interface()
            return

        try:
            pil_image = Image.open(file_path)
            self.display_image(pil_image)
            self.decode_and_display(pil_image, "image")
        except Exception as e:
            self.update_result_text(f"无法打开或解码图片: {e}")
        
        self.clear_button.configure(state="normal")

    def screen_shot_scan(self):
        self.clear_interface(is_starting_new_task=True)
        self.update_result_text("请拖动鼠标选择截图区域...")
        
        self.withdraw()
        self.after(100, self.create_screen_selection_overlay)

    def create_screen_selection_overlay(self):
        overlay = ScreenSelectionOverlay(self, self.on_screenshot_selection)
    
    def on_screenshot_selection(self, top_x, top_y, width, height):
        """Callback function for when a screen region is selected."""
        self.deiconify() # Ensure the main window is visible again

        if width <= 0 or height <= 0:
            self.clear_interface() # Reset the entire UI
            self.update_result_text("截图操作已取消。")
            self.clear_button.configure(state="normal") # Allow clearing the cancellation message
            return

        try:
            monitor = {"top": top_y, "left": top_x, "width": width, "height": height}
            with mss.mss() as sct:
                sct_img = sct.grab(monitor)
                pil_image = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            
            self.display_image(pil_image)
            self.decode_and_display(pil_image, "screenshot")
        except Exception as e:
            self.update_result_text(f"截屏或解码失败: {e}")
        
        self.clear_button.configure(state="normal")

    def start_realtime_screen_scan(self):
        self.clear_interface(is_starting_new_task=True)
        self.update_result_text("启动实时区域扫描... 请拖动透明窗口到二维码上方。")
        
        self.scanning = True
        self.clear_button.configure(state="normal")
        
        if not self.overlay_window:
            self.overlay_window = OverlayWindow(self)
        
        self.scan_thread = threading.Thread(target=self._realtime_screen_scan_loop, daemon=True)
        self.scan_thread.start()

    def _realtime_screen_scan_loop(self):
        try:
            with mss.mss() as sct:
                while self.scanning and self.overlay_window:
                    try:
                        x = self.overlay_window.winfo_x()
                        y = self.overlay_window.winfo_y()
                        width = self.overlay_window.winfo_width()
                        height = self.overlay_window.winfo_height()
                        
                        monitor = {"top": y, "left": x, "width": width, "height": height}

                        sct_img = sct.grab(monitor)
                        pil_image = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                        
                        self.display_image(pil_image)
                        self.decode_and_display(pil_image, "realtime_screen")

                    except Exception:
                        pass
                    
                    time.sleep(0.1)
        except Exception as e:
            self.update_result_text(f"实时扫描线程出错: {e}")
        finally:
            self.scanning = False
            self.after(0, self.clear_button.configure, {"state": "normal"})
            if self.overlay_window:
                self.overlay_window.destroy()
                self.overlay_window = None
        
    def clear_interface(self, is_starting_new_task=False):
        if self.scanning:
            self.scanning = False
            if self.scan_thread and self.scan_thread.is_alive():
                self.scan_thread.join(timeout=0.5)
        
        if self.overlay_window:
            self.overlay_window.destroy()
            self.overlay_window = None
            
        if not is_starting_new_task:
            self.image_label.configure(image=None, text="图像显示区域\n\n欢迎使用！请从下方选择一个功能。")
            self.update_result_text("")
            self.clear_button.configure(state="disabled")
        
    def decode_and_display(self, image, source_type="image"):
        found_qr = False
        try:
            decoded_objects = decode(image)
            if decoded_objects:
                results = []
                for obj in decoded_objects:
                    results.append(f"类型: {obj.type}\n数据: {obj.data.decode('utf-8')}\n")
                self.update_result_text("".join(results))
                found_qr = True
                
                if source_type == "image" or source_type == "screenshot":
                     self.display_image(image)
            else:
                if source_type == "image" or source_type == "screenshot":
                    self.update_result_text("未检测到二维码。")
        except Exception as e:
            self.update_result_text(f"解码时出错: {e}")
        
        if source_type == "realtime_screen" and self.overlay_window:
            self.overlay_window.update_border(found_qr)


    def display_image(self, pil_image):
        """Resizes and displays a PIL image in the CTkLabel."""
        if not self.image_label.winfo_exists(): return

        label_width = self.image_label.winfo_width()
        label_height = self.image_label.winfo_height()
        
        if label_width < 2 or label_height < 2:
            label_width, label_height = 700, 450

        img_copy = pil_image.copy()
        img_copy.thumbnail((label_width, label_height), Image.Resampling.LANCZOS)
        
        ctk_image = ctk.CTkImage(light_image=img_copy, dark_image=img_copy, size=img_copy.size)
        
        self.image_label.configure(image=ctk_image, text="")
        self.image_label.image = ctk_image

    def update_result_text(self, text):
        """Clears and inserts text into the result textbox."""
        if not self.result_text.winfo_exists(): return
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)

class OverlayWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.geometry("300x300+100+100")
        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.5)
        self.configure(fg_color="blue")

        self.info_label = ctk.CTkLabel(self, text="拖动此窗口", text_color="white")
        self.info_label.pack(expand=True, fill="both")

        self._start_x = 0
        self._start_y = 0

        self.bind("<ButtonPress-1>", self.on_press)
        self.bind("<B1-Motion>", self.on_drag)

    def on_press(self, event):
        self._start_x = event.x
        self._start_y = event.y

    def on_drag(self, event):
        x = self.winfo_x() - self._start_x + event.x
        y = self.winfo_y() - self._start_y + event.y
        self.geometry(f"+{x}+{y}")

    def update_border(self, found_qr):
        color = "green" if found_qr else "blue"
        if self.cget("fg_color") != color:
            self.configure(fg_color=color)

class ScreenSelectionOverlay(ctk.CTkToplevel):
    def __init__(self, master, callback):
        super().__init__(master)
        self.master_app = master
        self.callback = callback

        self.overrideredirect(True)
        self.attributes("-alpha", 0.3)
        self.configure(fg_color="black")
        self.attributes("-topmost", True)

        # Get screen dimensions and set geometry
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}+0+0")

        self.canvas = ctk.CTkCanvas(self, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.configure(cursor="crosshair")

        self.start_x = None
        self.start_y = None
        self.rect = None

        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", self.cancel_selection)

    def on_press(self, event):
        self.start_x = self.canvas.canvasx(event.x)
        self.start_y = self.canvas.canvasy(event.y)
        if self.rect:
            self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=2)

    def on_drag(self, event):
        cur_x = self.canvas.canvasx(event.x)
        cur_y = self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        end_x = self.canvas.canvasx(event.x)
        end_y = self.canvas.canvasy(event.y)

        # Ensure top-left and bottom-right coordinates
        x1 = min(self.start_x, end_x)
        y1 = min(self.start_y, end_y)
        x2 = max(self.start_x, end_x)
        y2 = max(self.start_y, end_y)
        
        width = x2 - x1
        height = y2 - y1

        self.destroy()
        self.callback(int(x1), int(y1), int(width), int(height))

    def cancel_selection(self, event=None):
        self.destroy()
        self.callback(0, 0, 0, 0) # Signal cancellation

if __name__ == "__main__":
    app = QRCodeScannerApp()
    app.mainloop()
