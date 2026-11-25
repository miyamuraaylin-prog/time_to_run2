import io
import mimetypes
import os
import shutil
import tempfile
import tkinter as tk
import wave
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import mysql.connector

from auth import verificar
from db import DatabaseConnectionError, execute, execute_transaction, query


BG = "#f3f6f8"
GREEN = "#075e54"
LIGHT_GREEN = "#d9fdd3"
WHITE = "#ffffff"
TEXT = "#202c33"
MUTED = "#667781"
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_RECORDING_SECONDS = 180
SAMPLE_RATE = 22050


class ComuApp:
    def __init__(self, root):
        self.root = root
        self.root.title("ComuApp")
        self.root.geometry("1020x680")
        self.root.minsize(760, 500)
        self.root.configure(bg=BG)
        self.user = None
        self.contacts = []
        self.selected_contact = None
        self._poll_after_id = None
        self._record_stream = None
        self._record_timeout_id = None
        self._record_chunks = []
        self._record_error = None
        self._audio_temp_dir = tempfile.mkdtemp(prefix="comuapp_audio_")
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self.show_login()

    def show_login(self):
        self._clear()
        panel = tk.Frame(self.root, bg=WHITE, padx=38, pady=34)
        panel.place(relx=0.5, rely=0.5, anchor="center")

        tk.Label(panel, text="ComuApp", bg=WHITE, fg=GREEN,
                 font=("Segoe UI", 26, "bold")).pack(pady=(0, 4))
        tk.Label(panel, text="Mensagens simples, perto de si",
                 bg=WHITE, fg=MUTED, font=("Segoe UI", 10)).pack(pady=(0, 24))

        tk.Label(panel, text="Utilizador", bg=WHITE, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.username_entry = ttk.Entry(panel, width=34)
        self.username_entry.pack(pady=(5, 14), ipady=5)

        tk.Label(panel, text="Palavra-passe", bg=WHITE, fg=TEXT,
                 font=("Segoe UI", 10, "bold")).pack(anchor="w")
        self.password_entry = ttk.Entry(panel, width=34, show="•")
        self.password_entry.pack(pady=(5, 20), ipady=5)
        self.password_entry.bind("<Return>", lambda _event: self.login())
        self.username_entry.bind("<Return>", lambda _event: self.password_entry.focus_set())

        ttk.Button(panel, text="Entrar", command=self.login).pack(fill="x", ipady=5)
        self.username_entry.focus_set()

    def login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get()
        if not username or not password:
            messagebox.showwarning("Dados em falta", "Introduza o utilizador e a palavra-passe.")
            return

        try:
            user = query(
                "SELECT id, nome, username, password_hash FROM utilizadores "
                "WHERE username=%s AND ativo=1",
                (username,),
                one=True,
            )
        except (DatabaseConnectionError, mysql.connector.Error) as error:
            self._show_database_error(error)
            return

        if not user or not verificar(password, user["password_hash"]):
            messagebox.showerror("Acesso recusado", "Utilizador ou palavra-passe incorretos.")
            self.password_entry.delete(0, tk.END)
            self.password_entry.focus_set()
            return

        self.user = user
        try:
            execute(
                """CREATE TABLE IF NOT EXISTS mensagens (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    remetente_id INT NOT NULL,
                    destinatario_id INT NOT NULL,
                    texto TEXT NOT NULL,
                    enviada_em DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    lida TINYINT(1) NOT NULL DEFAULT 0,
                    INDEX idx_mensagens_conversa (remetente_id, destinatario_id, enviada_em),
                    CONSTRAINT fk_mensagens_remetente
                        FOREIGN KEY (remetente_id) REFERENCES utilizadores(id) ON DELETE CASCADE,
                    CONSTRAINT fk_mensagens_destinatario
                        FOREIGN KEY (destinatario_id) REFERENCES utilizadores(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
            )
            execute(
                """CREATE TABLE IF NOT EXISTS mensagens_audios (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    mensagem_id INT NOT NULL UNIQUE,
                    nome_ficheiro VARCHAR(255) NOT NULL,
                    tipo_mime VARCHAR(100) NOT NULL,
                    conteudo LONGBLOB NOT NULL,
                    CONSTRAINT fk_mensagens_audios_mensagem
                        FOREIGN KEY (mensagem_id) REFERENCES mensagens(id) ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"""
            )
        except (DatabaseConnectionError, mysql.connector.Error) as error:
            self._show_database_error(error)
            return
        self.show_messenger()

    def show_messenger(self):
        self._clear()
        shell = tk.Frame(self.root, bg=WHITE)
        shell.pack(fill="both", expand=True)
        shell.grid_columnconfigure(1, weight=1)
        shell.grid_rowconfigure(0, weight=1)

        sidebar = tk.Frame(shell, bg=WHITE, width=300)
        sidebar.grid(row=0, column=0, sticky="nsew")
        sidebar.grid_propagate(False)

        brand = tk.Frame(sidebar, bg=GREEN, padx=16, pady=14)
        brand.pack(fill="x")
        tk.Label(brand, text="ComuApp", bg=GREEN, fg=WHITE,
                 font=("Segoe UI", 18, "bold")).pack(anchor="w")
        tk.Label(brand, text=self.user["nome"], bg=GREEN, fg="#d7f5ef",
                 font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))

        self.search_var = tk.StringVar()
        search = ttk.Entry(sidebar, textvariable=self.search_var)
        search.pack(fill="x", padx=12, pady=12, ipady=5)
        search.insert(0, "")
        self.search_var.trace_add("write", lambda *_args: self._render_contacts())

        self.contact_list = tk.Listbox(
            sidebar, borderwidth=0, highlightthickness=0, activestyle="none",
            font=("Segoe UI", 10), bg=WHITE, fg=TEXT,
            selectbackground="#e9edef", selectforeground=TEXT,
        )
        self.contact_list.pack(fill="both", expand=True)
        self.contact_list.bind("<<ListboxSelect>>", self._select_contact)

        tk.Button(sidebar, text="Terminar sessão", command=self.logout,
                  bg=WHITE, fg=MUTED, relief="flat", anchor="w",
                  padx=16, pady=12, cursor="hand2").pack(fill="x")

        conversation = tk.Frame(shell, bg=BG)
        conversation.grid(row=0, column=1, sticky="nsew")
        conversation.grid_rowconfigure(1, weight=1)
        conversation.grid_columnconfigure(0, weight=1)

        self.chat_header = tk.Frame(conversation, bg=WHITE, padx=18, pady=13)
        self.chat_header.grid(row=0, column=0, sticky="ew")
        self.header_name = tk.Label(self.chat_header, text="Escolha uma conversa",
                                    bg=WHITE, fg=TEXT, font=("Segoe UI", 13, "bold"))
        self.header_name.pack(anchor="w")
        self.header_status = tk.Label(self.chat_header, text="As suas mensagens, num só lugar",
                                      bg=WHITE, fg=MUTED, font=("Segoe UI", 9))
        self.header_status.pack(anchor="w", pady=(2, 0))

        chat_area = tk.Frame(conversation, bg=BG)
        chat_area.grid(row=1, column=0, sticky="nsew")
        chat_area.grid_rowconfigure(0, weight=1)
        chat_area.grid_columnconfigure(0, weight=1)
        self.chat_canvas = tk.Canvas(chat_area, bg=BG, highlightthickness=0)
        self.chat_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(chat_area, orient="vertical", command=self.chat_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.chat_canvas.configure(yscrollcommand=scrollbar.set)
        self.message_frame = tk.Frame(self.chat_canvas, bg=BG)
        self.message_window = self.chat_canvas.create_window(
            (0, 0), window=self.message_frame, anchor="nw"
        )
        self.message_frame.bind("<Configure>", self._update_scroll_region)
        self.chat_canvas.bind("<Configure>", self._resize_message_frame)

        composer = tk.Frame(conversation, bg="#f0f2f5", padx=12, pady=12)
        composer.grid(row=2, column=0, sticky="ew")
        composer.grid_columnconfigure(2, weight=1)
        self.audio_button = ttk.Button(composer, text="Áudio", command=self.choose_audio)
        self.audio_button.grid(row=0, column=0, padx=(0, 6), ipady=5)
        self.record_button = ttk.Button(composer, text="Gravar", command=self.toggle_recording)
        self.record_button.grid(row=0, column=1, padx=(0, 10), ipady=5)
        self.message_entry = ttk.Entry(composer, font=("Segoe UI", 11))
        self.message_entry.grid(row=0, column=2, sticky="ew", padx=(0, 10), ipady=8)
        self.message_entry.bind("<Return>", lambda _event: self.send_message())
        ttk.Button(composer, text="Enviar", command=self.send_message).grid(row=0, column=3, ipady=5)
        self.audio_status = tk.Label(composer, text="", bg="#f0f2f5", fg=MUTED,
                                     font=("Segoe UI", 9))
        self.audio_status.grid(row=1, column=0, columnspan=4, sticky="w", pady=(5, 0))

        self.refresh_contacts()
        self._poll_after_id = self.root.after(2500, self._poll)

    def refresh_contacts(self):
        try:
            self.contacts = query(
                "SELECT id, nome, username FROM utilizadores "
                "WHERE ativo=1 AND id<>%s ORDER BY nome",
                (self.user["id"],),
            )
            for contact in self.contacts:
                latest = query(
                    """SELECT m.texto, m.enviada_em, a.nome_ficheiro
                       FROM mensagens m
                       LEFT JOIN mensagens_audios a ON a.mensagem_id=m.id
                       WHERE (m.remetente_id=%s AND m.destinatario_id=%s)
                          OR (m.remetente_id=%s AND m.destinatario_id=%s)
                       ORDER BY m.enviada_em DESC, m.id DESC LIMIT 1""",
                    (self.user["id"], contact["id"], contact["id"], self.user["id"]),
                    one=True,
                )
                unread = query(
                    """SELECT COUNT(*) AS total FROM mensagens
                       WHERE remetente_id=%s AND destinatario_id=%s AND lida=0""",
                    (contact["id"], self.user["id"]),
                    one=True,
                )
                contact["ultima_mensagem"] = (
                    f"Áudio: {latest['nome_ficheiro']}" if latest and latest["nome_ficheiro"]
                    else latest["texto"] if latest else ""
                )
                contact["nao_lidas"] = unread["total"] if unread else 0
        except (DatabaseConnectionError, mysql.connector.Error) as error:
            self._show_database_error(error)
            return

        self._render_contacts()
        if self.selected_contact and not any(
            item["id"] == self.selected_contact["id"] for item in self.contacts
        ):
            self.selected_contact = None
            self._render_messages([])

    def _render_contacts(self):
        if not hasattr(self, "contact_list"):
            return
        selected_id = self.selected_contact["id"] if self.selected_contact else None
        search = self.search_var.get().strip().casefold()
        self.visible_contacts = [
            contact for contact in self.contacts
            if search in contact["nome"].casefold() or search in contact["username"].casefold()
        ]
        self.contact_list.delete(0, tk.END)
        selection_index = None
        for index, contact in enumerate(self.visible_contacts):
            preview = contact.get("ultima_mensagem", "").replace("\n", " ")
            if len(preview) > 27:
                preview = preview[:27] + "…"
            label = contact["nome"]
            if contact.get("nao_lidas"):
                label += "  •"
            if preview:
                label += "\n" + preview
            self.contact_list.insert(tk.END, label)
            if contact["id"] == selected_id:
                selection_index = index
        if selection_index is not None:
            self.contact_list.selection_set(selection_index)

    def _select_contact(self, _event=None):
        selection = self.contact_list.curselection()
        if not selection:
            return
        self.selected_contact = self.visible_contacts[selection[0]]
        self.header_name.config(text=self.selected_contact["nome"])
        self.header_status.config(text=self.selected_contact["username"])
        self.message_entry.focus_set()
        self._load_messages()

    def _load_messages(self):
        if not self.selected_contact:
            return
        try:
            execute(
                "UPDATE mensagens SET lida=1 WHERE remetente_id=%s "
                "AND destinatario_id=%s AND lida=0",
                (self.selected_contact["id"], self.user["id"]),
            )
            messages = query(
                """SELECT m.id, m.remetente_id, m.texto, m.enviada_em,
                          a.id AS audio_id, a.nome_ficheiro
                   FROM mensagens m
                   LEFT JOIN mensagens_audios a ON a.mensagem_id=m.id
                   WHERE (m.remetente_id=%s AND m.destinatario_id=%s)
                      OR (m.remetente_id=%s AND m.destinatario_id=%s)
                   ORDER BY m.enviada_em ASC, m.id ASC""",
                (self.user["id"], self.selected_contact["id"],
                 self.selected_contact["id"], self.user["id"]),
            )
        except (DatabaseConnectionError, mysql.connector.Error) as error:
            self._show_database_error(error)
            return
        self._render_messages(messages)

    def _render_messages(self, messages):
        for child in self.message_frame.winfo_children():
            child.destroy()
        self.message_frame.grid_columnconfigure(0, weight=1)
        for row, message in enumerate(messages):
            outgoing = message["remetente_id"] == self.user["id"]
            line = tk.Frame(self.message_frame, bg=BG)
            line.grid(row=row, column=0, sticky="ew", padx=18, pady=4)
            line.grid_columnconfigure(0, weight=1)
            bubble_color = LIGHT_GREEN if outgoing else WHITE
            bubble = tk.Frame(line, bg=bubble_color, padx=11, pady=7)
            bubble.grid(row=0, column=0, sticky="e" if outgoing else "w")
            if message["audio_id"]:
                tk.Label(
                    bubble, text=message["nome_ficheiro"], justify="left", anchor="w",
                    wraplength=max(180, self.chat_canvas.winfo_width() - 150),
                    bg=bubble_color, fg=TEXT, font=("Segoe UI", 10),
                ).pack(anchor="w")
                tk.Button(
                    bubble, text="▶  Ouvir áudio", command=lambda audio_id=message["audio_id"]:
                    self.play_audio(audio_id), bg=bubble_color, fg=GREEN,
                    relief="flat", cursor="hand2",
                ).pack(anchor="w", pady=(3, 0))
            else:
                tk.Label(
                    bubble, text=message["texto"], justify="left", anchor="w",
                    wraplength=max(180, self.chat_canvas.winfo_width() - 150),
                    bg=bubble_color, fg=TEXT, font=("Segoe UI", 10),
                ).pack(anchor="w")
            stamp = message["enviada_em"]
            if hasattr(stamp, "strftime"):
                stamp = stamp.strftime("%H:%M")
            tk.Label(bubble, text=str(stamp), bg=LIGHT_GREEN if outgoing else WHITE,
                     fg=MUTED, font=("Segoe UI", 8)).pack(anchor="e", pady=(3, 0))
        self.message_frame.update_idletasks()
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))
        self.chat_canvas.yview_moveto(1)

    def send_message(self):
        if not self.selected_contact:
            messagebox.showinfo("Sem conversa", "Escolha uma pessoa antes de enviar uma mensagem.")
            return
        text = self.message_entry.get().strip()
        if not text:
            return
        try:
            execute(
                "INSERT INTO mensagens (remetente_id, destinatario_id, texto) VALUES (%s,%s,%s)",
                (self.user["id"], self.selected_contact["id"], text),
            )
        except (DatabaseConnectionError, mysql.connector.Error) as error:
            self._show_database_error(error)
            return
        self.message_entry.delete(0, tk.END)
        self.refresh_contacts()
        self._load_messages()

    def choose_audio(self):
        if not self.selected_contact:
            messagebox.showinfo("Sem conversa", "Escolha uma pessoa antes de enviar um áudio.")
            return
        path = filedialog.askopenfilename(
            title="Escolher áudio",
            filetypes=[
                ("Ficheiros de áudio", "*.wav *.mp3 *.m4a *.ogg *.flac *.aac *.opus"),
                ("Todos os ficheiros", "*.*"),
            ],
        )
        if not path:
            return
        try:
            size = os.path.getsize(path)
            if size > MAX_AUDIO_BYTES:
                messagebox.showwarning("Áudio demasiado grande", "O tamanho máximo é 10 MB.")
                return
            with open(path, "rb") as audio_file:
                contents = audio_file.read()
        except OSError as error:
            messagebox.showerror("Erro ao abrir áudio", str(error))
            return
        if len(contents) > MAX_AUDIO_BYTES:
            messagebox.showwarning("Áudio demasiado grande", "O tamanho máximo é 10 MB.")
            return

        mime_type = mimetypes.guess_type(path)[0]
        if not mime_type or not mime_type.startswith("audio/"):
            messagebox.showerror("Ficheiro inválido", "Escolha um ficheiro de áudio válido.")
            return
        self._send_audio(contents, os.path.basename(path), mime_type)

    def toggle_recording(self):
        if self._record_stream:
            self._stop_recording(send_audio=True)
            return
        if not self.selected_contact:
            messagebox.showinfo("Sem conversa", "Escolha uma pessoa antes de gravar um áudio.")
            return
        try:
            import numpy
            import sounddevice
        except ImportError as error:
            messagebox.showerror(
                "Gravação indisponível",
                f"Instale as dependências com «py -m pip install -r requirements.txt».\n\n{error}",
            )
            return

        self._numpy = numpy
        self._sounddevice = sounddevice
        self._record_chunks = []
        self._record_error = None
        stream = None
        try:
            stream = sounddevice.InputStream(
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype="int16",
                callback=self._capture_audio,
            )
            stream.start()
        except (sounddevice.PortAudioError, OSError) as error:
            error_message = str(error)
            if stream:
                try:
                    stream.close()
                except (sounddevice.PortAudioError, OSError) as close_error:
                    error_message += f"\nTambém não foi possível fechar a gravação: {close_error}"
            messagebox.showerror("Erro ao iniciar gravação", error_message)
            return

        self._record_stream = stream
        self.record_button.config(text="Parar e enviar")
        self.audio_button.config(state="disabled")
        self.audio_status.config(text="A gravar… prima «Parar e enviar» para terminar.")
        self._record_timeout_id = self.root.after(
            MAX_RECORDING_SECONDS * 1000,
            lambda: self._stop_recording(send_audio=True),
        )

    def _capture_audio(self, audio_data, _frames, _time_info, status):
        if status:
            self._record_error = str(status)
        self._record_chunks.append(self._numpy.asarray(audio_data, dtype=self._numpy.int16).tobytes())

    def _stop_recording(self, send_audio):
        stream = self._record_stream
        if not stream:
            return
        self._record_stream = None
        if self._record_timeout_id:
            self.root.after_cancel(self._record_timeout_id)
            self._record_timeout_id = None

        stream_error = None
        try:
            stream.stop()
        except (self._sounddevice.PortAudioError, OSError) as error:
            stream_error = error
        try:
            stream.close()
        except (self._sounddevice.PortAudioError, OSError) as error:
            stream_error = error

        self.record_button.config(text="Gravar")
        self.audio_button.config(state="normal")
        self.audio_status.config(text="")
        if stream_error:
            messagebox.showerror("Erro na gravação", str(stream_error))
            return
        if self._record_error:
            messagebox.showwarning("Aviso na gravação", self._record_error)

        chunks = self._record_chunks
        self._record_chunks = []
        self._record_error = None
        if not send_audio or not chunks:
            return

        audio_buffer = io.BytesIO()
        with wave.open(audio_buffer, "wb") as audio_file:
            audio_file.setnchannels(1)
            audio_file.setsampwidth(2)
            audio_file.setframerate(SAMPLE_RATE)
            audio_file.writeframes(b"".join(chunks))
        filename = "audio_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".wav"
        self._send_audio(audio_buffer.getvalue(), filename, "audio/wav")

    def _send_audio(self, contents, filename, mime_type):
        if len(contents) > MAX_AUDIO_BYTES:
            messagebox.showwarning("Áudio demasiado grande", "O tamanho máximo é 10 MB.")
            return
        try:
            execute_transaction([
                (
                    "INSERT INTO mensagens (remetente_id, destinatario_id, texto) "
                    "VALUES (%s,%s,%s)",
                    (self.user["id"], self.selected_contact["id"], f"Áudio: {filename}"),
                ),
                (
                    "INSERT INTO mensagens_audios "
                    "(mensagem_id, nome_ficheiro, tipo_mime, conteudo) VALUES "
                    "(LAST_INSERT_ID(), %s, %s, %s)",
                    (filename, mime_type, contents),
                ),
            ])
        except (DatabaseConnectionError, mysql.connector.Error) as error:
            self._show_database_error(error)
            return
        self.refresh_contacts()
        self._load_messages()

    def play_audio(self, audio_id):
        try:
            audio = query(
                "SELECT nome_ficheiro, conteudo FROM mensagens_audios WHERE id=%s",
                (audio_id,),
                one=True,
            )
            if not audio:
                messagebox.showerror("Áudio indisponível", "O áudio já não está disponível.")
                return
            suffix = Path(audio["nome_ficheiro"]).suffix or ".audio"
            audio_path = Path(self._audio_temp_dir) / f"{audio_id}{suffix}"
            audio_path.write_bytes(audio["conteudo"])
            if hasattr(os, "startfile"):
                os.startfile(str(audio_path))
            else:
                import webbrowser
                if not webbrowser.open(audio_path.resolve().as_uri()):
                    messagebox.showerror("Erro ao reproduzir áudio", "Não foi possível abrir o áudio.")
        except (DatabaseConnectionError, mysql.connector.Error, OSError) as error:
            messagebox.showerror("Erro ao reproduzir áudio", str(error))

    def _poll(self):
        self._poll_after_id = None
        if not self.user or not self.root.winfo_exists():
            return
        self.refresh_contacts()
        if self.selected_contact:
            self._load_messages()
        self._poll_after_id = self.root.after(2500, self._poll)

    def _update_scroll_region(self, _event=None):
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _resize_message_frame(self, event):
        self.chat_canvas.itemconfigure(self.message_window, width=event.width)

    def _show_database_error(self, error):
        messagebox.showerror(
            "Erro de base de dados",
            f"Não foi possível concluir a operação.\n\n{error}",
        )

    def logout(self):
        if self._poll_after_id:
            self.root.after_cancel(self._poll_after_id)
            self._poll_after_id = None
        if self._record_stream:
            self._stop_recording(send_audio=False)
        self.user = None
        self.selected_contact = None
        self.show_login()

    def close(self):
        if self._record_stream:
            self._stop_recording(send_audio=False)
        try:
            shutil.rmtree(self._audio_temp_dir)
        except FileNotFoundError:
            pass
        except OSError as error:
            messagebox.showwarning(
                "Ficheiros temporários",
                f"Não foi possível remover os áudios temporários:\n{error}",
            )
        finally:
            self.root.destroy()

    def _clear(self):
        for child in self.root.winfo_children():
            child.destroy()


def main():
    root = tk.Tk()
    ComuApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
