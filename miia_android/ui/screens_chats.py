"""Lista de chats guardados: abrir uno anterior, borrarlo o empezar uno nuevo."""

from datetime import datetime

from kivy.metrics import dp

from . import theme
from .kit import Dialog, ask_yes_no, button, hrow, small, title


def _when(iso: str) -> str:
    try:
        d = datetime.fromisoformat(iso)
        return d.strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""


def open_chats(app):
    mem = app.engine.memory
    dlg = Dialog("Chats")
    dlg.add(small("Cada vez que abres la app empieza un chat nuevo. Aquí están los anteriores. "
                  "Si abres uno, MIIA retoma esa conversación."))
    dlg.add(button("Nuevo chat", lambda: (dlg.close(), app.new_chat()), "primary"))
    chats = mem.list_chats()
    if not chats:
        dlg.add(small("Todavía no hay charlas guardadas."))
    for ch in chats:
        current = ch["id"] == mem.current_chat
        label = ch["title"] + ("  (abierto)" if current else "")
        dlg.add(title(label))
        dlg.add(small(f"{_when(ch['start'])} · {ch['count']} mensajes"))

        def opener(cid=ch["id"]):
            dlg.close()
            app.open_saved_chat(cid)

        def deleter(cid=ch["id"], t=ch["title"]):
            def ans(yes):
                if yes:
                    app.delete_saved_chat(cid)
                    dlg.close()
                    open_chats(app)
            ask_yes_no("Borrar chat", f"¿Borrar «{t}»? No se puede deshacer.", ans, yes="Borrar", no="Cancelar")

        dlg.add(hrow(button("Abrir", opener, "secondary"), button("Borrar", deleter, "neutral")))
    dlg.open()
    return dlg
