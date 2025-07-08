import customtkinter as ctk
from PIL import Image
import cv2
import numpy as np
import mss
import threading
import time
from tkinter import filedialog
import sys

# Conditional import and setup for cross-platform QR decoding
if sys.platform == "win32":
    # Helper class to mimic the structure of pyzbar's decoded objects for Windows
    class DecodedObject:
        def __init__(self, data):
            self.type = 'QRCODE'
            self.data = data.encode('utf-8')
else:
    from pyzbar.pyzbar import decode

class QRCodeScannerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("全能二维码扫描器")
        self.geometry("800x600")

        # --- Platform-specific detector ---
        # Initialized lazily in _decode_image for Windows

        # --- State Variables ---
        self.scanning = False
        self.scan_thread = None
        self.overlay_window = None
        self.latest_scan_result = None
        self.updater_id = None
        self.last_decoded_data = None
        self.is_realtime_screen_scanning = False

        # --- UI Elements ---
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.pack(padx=10, pady=10, fill="both", expand=True)

        self.image_label = ctk.CTkLabel(self.main_frame, text="图像显示区域\n\n欢迎使用！请从下方选择一个功能。", justify="center")
        self.image_label.pack(pady=10, padx=10, fill="both", expand=True)

        self.result_text = ctk.CTkTextbox(self.main_frame, height=100)
        self.result_text.pack(pady=10, padx=10, fill="x")

        self.button_frame = ctk.CTkFrame(self)
        self.button_frame.pack(pady=10, padx=10, fill="x")

        # --- Configure Grid Layout for Buttons ---
        self.button_frame.grid_columnconfigure((0, 1, 2), weight=1)

        # --- Create Buttons ---
        self.camera_button = ctk.CTkButton(self.button_frame, text="摄像头实时扫描", command=self.start_camera_scan)
        self.upload_button = ctk.CTkButton(self.button_frame, text="上传图片扫描", command=self.upload_image_scan)
        self.screen_button = ctk.CTkButton(self.button_frame, text="选区截屏扫描", command=self.screen_shot_scan)
        self.realtime_screen_button = ctk.CTkButton(self.button_frame, text="实时区域扫描", command=self.start_realtime_screen_scan)
        self.copy_button = ctk.CTkButton(self.button_frame, text="复制数据", command=self.copy_result_to_clipboard, state="disabled")
        self.clear_button = ctk.CTkButton(self.button_frame, text="清空 / 返回", command=self.clear_interface, state="disabled")

        # --- Place Buttons in Grid ---
        self.camera_button.grid(row=0, column=0, padx=5, pady=5, sticky="ew")
        self.upload_button.grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        self.screen_button.grid(row=0, column=2, padx=5, pady=5, sticky="ew")
        self.realtime_screen_button.grid(row=1, column=0, padx=5, pady=5, sticky="ew")
        self.copy_button.grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        self.clear_button.grid(row=1, column=2, padx=5, pady=5, sticky="ew")

        # --- Protocol Binding ---
        self.protocol("WM_DELETE_WINDOW", self._on_closing)

    # --- Scan Methods ---

    def start_camera_scan(self):
        self.clear_interface(is_starting_new_task=True)
        self._set_scan_buttons_state("disabled")
        self.update_result_text("正在启动摄像头...")
        self.scanning = True
        self.scan_thread = threading.Thread(target=self._camera_scan_loop, daemon=True)
        self.scan_thread.start()
        self._ui_updater_loop()

    def _camera_scan_loop(self):
        cap = None
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                error_message = "未检测到摄像头，或摄像头正被其他程序占用。"
                if sys.platform == "darwin":
                    error_message += "\n\nmacOS用户请注意: 请检查系统设置 -> 隐私与安全性 -> 摄像头，确保本应用已被授权访问。"
                self.latest_scan_result = ("error", error_message)
                return
            while self.scanning:
                ret, frame = cap.read()
                if not ret:
                    self.latest_scan_result = ("error", "无法从摄像头捕获画面。")
                    break
                frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                pil_image = Image.fromarray(frame_rgb)
                self.latest_scan_result = pil_image # Put raw image in the inbox
                time.sleep(0.04)
        except Exception as e:
            self.latest_scan_result = ("error", f"摄像头初始化或读取时出错: {e}")
        finally:
            if cap:
                cap.release()
            self.scanning = False

    def start_realtime_screen_scan(self):
        self.clear_interface(is_starting_new_task=True)
        self._set_scan_buttons_state("disabled")
        self.update_result_text("启动实时区域扫描... 请拖动透明窗口到二维码上方。")
        self.scanning = True
        self.is_realtime_screen_scanning = True
        if not self.overlay_window or not self.overlay_window.winfo_exists():
            self.overlay_window = OverlayWindow(self)
        self.focus_force()
        self.scan_thread = threading.Thread(target=self._realtime_screen_scan_loop, daemon=True)
        self.scan_thread.start()
        self._ui_updater_loop()

    def _realtime_screen_scan_loop(self):
        try:
            with mss.mss() as sct:
                while self.scanning:
                    if not self.overlay_window or not self.overlay_window.winfo_exists():
                        break
                    try:
                        monitor = self.overlay_window.get_monitor()
                        sct_img = sct.grab(monitor)
                        pil_image = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                        self.latest_scan_result = pil_image # Put raw image in the inbox
                    except Exception:
                        pass
                    time.sleep(0.1)
        finally:
            self.scanning = False

    def upload_image_scan(self):
        self.clear_interface(is_starting_new_task=True)
        self._set_scan_buttons_state("disabled")
        file_path = filedialog.askopenfilename(title="选择一个二维码图片", filetypes=(("Image files", "*.png *.jpg *.jpeg *.bmp *.gif"), ("All files", "*.*" )))
        if not file_path:
            self.clear_interface()
            return
        try:
            pil_image = Image.open(file_path)
            self.display_image(pil_image)
            decoded_objects = self._decode_image(pil_image)
            if decoded_objects:
                self.last_decoded_data = decoded_objects[0].data.decode('utf-8')
                results = [f"类型: {obj.type}\n数据: {obj.data.decode('utf-8')}\n" for obj in decoded_objects]
                self.update_result_text("".join(results))
                self.copy_button.configure(state="normal")
            else:
                self.last_decoded_data = None
                self.copy_button.configure(state="disabled")
                self.update_result_text("未检测到二维码。")
        except Exception as e:
            self.update_result_text(f"无法打开或解码图片: {e}")
        self.clear_button.configure(state="normal")

    def screen_shot_scan(self):
        self.clear_interface(is_starting_new_task=True)
        self._set_scan_buttons_state("disabled")
        self.update_result_text("请拖动鼠标选择截图区域...")
        self.withdraw()
        self.after(200, lambda: ScreenSelectionOverlay(self, self.on_screenshot_selection))

    def on_screenshot_selection(self, top_x, top_y, width, height):
        self.deiconify()
        if width <= 0 or height <= 0:
            self.clear_interface()
            self.update_result_text("截图操作已取消。")
            return
        try:
            monitor = {"top": top_y, "left": top_x, "width": width, "height": height}
            with mss.mss() as sct:
                sct_img = sct.grab(monitor)
                pil_image = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
            self.display_image(pil_image)
            decoded_objects = self._decode_image(pil_image)
            if decoded_objects:
                self.last_decoded_data = decoded_objects[0].data.decode('utf-8')
                results = [f"类型: {obj.type}\n数据: {obj.data.decode('utf-8')}\n" for obj in decoded_objects]
                self.update_result_text("".join(results))
                self.copy_button.configure(state="normal")
            else:
                self.last_decoded_data = None
                self.copy_button.configure(state="disabled")
                self.update_result_text("未检测到二维码。")
        except Exception as e:
            self.update_result_text(f"截屏或解码失败: {e}")
        self.clear_button.configure(state="normal")

    def copy_result_to_clipboard(self):
        if self.last_decoded_data:
            self.clipboard_clear()
            self.clipboard_append(self.last_decoded_data)
            self.update_result_text(f"已复制到剪贴板:\n{self.last_decoded_data}")

    # --- UI and State Management ---

    def _ui_updater_loop(self):
        if not self.scanning:
            self.updater_id = None
            return

        if self.latest_scan_result:
            scan_data = self.latest_scan_result
            self.latest_scan_result = None

            if isinstance(scan_data, tuple) and scan_data[0] == "error":
                self.update_result_text(scan_data[1])
                self.scanning = False
            elif isinstance(scan_data, Image.Image):
                pil_image = scan_data
                decoded_objects = self._decode_image(pil_image)
                self.display_image(pil_image)
                found_qr = bool(decoded_objects)
                if found_qr:
                    self.last_decoded_data = decoded_objects[0].data.decode('utf-8')
                    results = [f"类型: {obj.type}\n数据: {obj.data.decode('utf-8')}\n" for obj in decoded_objects]
                    self.update_result_text("".join(results))
                    self.copy_button.configure(state="normal")
                else:
                    self.last_decoded_data = None
                    self.copy_button.configure(state="disabled")
                if self.overlay_window and self.overlay_window.winfo_exists():
                    self.overlay_window.update_border(found_qr)

        self.updater_id = self.after(100, self._ui_updater_loop)

    def clear_interface(self, is_starting_new_task=False):
        self.scanning = False
        self.scan_thread = None
        if self.updater_id:
            self.after_cancel(self.updater_id)
            self.updater_id = None
        if self.overlay_window and self.overlay_window.winfo_exists():
            self.overlay_window.destroy()
        self.overlay_window = None
        self.last_decoded_data = None
        self.is_realtime_screen_scanning = False
        self.copy_button.configure(state="disabled")
        if not is_starting_new_task:
            self._reset_ui_to_initial_state()
        else:
            self.clear_button.configure(state="normal")

    def _reset_ui_to_initial_state(self):
        # Destroy and recreate the image label to prevent TclError
        self.image_label.destroy()
        self.image_label = ctk.CTkLabel(self.main_frame, text="图像显示区域\n\n欢迎使用！请从下方选择一个功能。", justify="center")
        self.image_label.pack(pady=10, padx=10, fill="both", expand=True)
        # Re-stack the result text below the new image label
        self.result_text.pack_forget()
        self.result_text.pack(pady=10, padx=10, fill="x")

        self.update_result_text("")
        self.clear_button.configure(state="disabled")
        self._set_scan_buttons_state("normal")

    def _set_scan_buttons_state(self, state):
        """Enable or disable all scan-initiating buttons."""
        self.camera_button.configure(state=state)
        self.upload_button.configure(state=state)
        self.screen_button.configure(state=state)
        self.realtime_screen_button.configure(state=state)

    def _on_closing(self):
        """Handle the window closing event gracefully."""
        self.clear_interface()
        self.destroy()

    def _decode_image(self, image):
        try:
            if sys.platform == "win32":
                # Initialize detector only when needed on Windows
                if not hasattr(self, 'barcode_detector'):
                    self.barcode_detector = cv2.barcode.BarcodeDetector()
                cv_image = np.array(image.convert('RGB'))
                ok, decoded_info, _, _ = self.barcode_detector.detectAndDecodeWithType(cv_image)
                if ok and decoded_info:
                    return [DecodedObject(decoded_info[0])]
                else:
                    return []
            else:
                return decode(image)
        except Exception:
            return []

    def display_image(self, pil_image):
        if not self.image_label.winfo_exists(): return
        label_width, label_height = self.image_label.winfo_width(), self.image_label.winfo_height()
        if label_width < 2 or label_height < 2: label_width, label_height = 700, 450
        img_copy = pil_image.copy()
        img_copy.thumbnail((label_width, label_height), Image.Resampling.BILINEAR)
        ctk_image = ctk.CTkImage(light_image=img_copy, dark_image=img_copy, size=img_copy.size)
        self.image_label.configure(image=ctk_image, text="")
        self.image_label.image = ctk_image

    def update_result_text(self, text):
        if not self.result_text.winfo_exists(): return
        self.result_text.delete("1.0", "end")
        self.result_text.insert("1.0", text)

class OverlayWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.geometry("300x300+100+100")
        self.overrideredirect(True)
        self.transient(master) # Set as a transient window to the master

        # Platform-specific attributes to prevent focus stealing
        if sys.platform == "darwin":  # macOS
            self.attributes("-type", "utility")

        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.5)
        self.configure(fg_color="blue")
        self.info_label = ctk.CTkLabel(self, text="拖动此窗口", text_color="white")
        self.info_label.pack(expand=True, fill="both")
        self._start_x, self._start_y = 0, 0
        self.bind("<ButtonPress-1>", self.on_press)
        self.bind("<B1-Motion>", self.on_drag)
        self.bind("<ButtonRelease-1>", self.on_release)

    def on_press(self, event):
        self._start_x, self._start_y = event.x, event.y

    def on_drag(self, event):
        x = self.winfo_x() - self._start_x + event.x
        y = self.winfo_y() - self._start_y + event.y
        self.geometry(f"+{x}+{y}")

    def on_release(self, event):
        self.master.focus_force()

    def get_monitor(self):
        return {"top": self.winfo_y(), "left": self.winfo_x(), "width": self.winfo_width(), "height": self.winfo_height()}

    def update_border(self, found_qr):
        color = "green" if found_qr else "blue"
        if self.cget("fg_color") != color: self.configure(fg_color=color)

class ScreenSelectionOverlay(ctk.CTkToplevel):
    def __init__(self, master, callback):
        super().__init__(master)
        self.callback = callback
        self.overrideredirect(True)
        self.attributes("-alpha", 0.3)
        self.configure(fg_color="black")
        self.attributes("-topmost", True)
        screen_width, screen_height = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{screen_width}x{screen_height}+0+0")
        self.canvas = ctk.CTkCanvas(self, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack(fill="both", expand=True)
        self.start_x, self.start_y, self.rect = None, None, None
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.bind("<Escape>", lambda e: self.cancel_selection())

    def on_press(self, event):
        self.start_x, self.start_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        if self.rect: self.canvas.delete(self.rect)
        self.rect = self.canvas.create_rectangle(self.start_x, self.start_y, self.start_x, self.start_y, outline="red", width=2)

    def on_drag(self, event):
        cur_x, cur_y = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        self.canvas.coords(self.rect, self.start_x, self.start_y, cur_x, cur_y)

    def on_release(self, event):
        x1, y1 = min(self.start_x, self.canvas.canvasx(event.x)), min(self.start_y, self.canvas.canvasy(event.y))
        x2, y2 = max(self.start_x, self.canvas.canvasx(event.x)), max(self.start_y, self.canvas.canvasy(event.y))
        self.destroy()
        self.callback(int(x1), int(y1), int(x2 - x1), int(y2 - y1))

    def cancel_selection(self):
        self.destroy()
        self.callback(0, 0, 0, 0)

if __name__ == "__main__":
    try:
        app = QRCodeScannerApp()
        app.mainloop()
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()