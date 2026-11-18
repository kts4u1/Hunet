"""프로그램 화면이 오류 없이 열리고 닫히는지 확인합니다."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import customtkinter as ctk  # noqa: E402

from hunet_auto.app import App  # noqa: E402

ctk.set_appearance_mode("light")
root = ctk.CTk()
app = App(root)
app._cancel_countdown()
root.after(1500, app.on_close)
root.mainloop()
print("GUI OK")
