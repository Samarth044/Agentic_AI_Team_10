"""In-app notifications written by agents and human actions."""

from __future__ import annotations

from . import db


def notify(user_id: str | None, text: str, link: str = "") -> None:
    if user_id:
        db.insert("notifications", {"user_id": user_id, "text": text, "link": link, "ts": db.now()})


def notify_student(student_id: str, text: str, link: str = "") -> None:
    s = db.get_student(student_id)
    if s:
        notify(s["user_id"], text, link)


def notify_role(role: str, text: str, link: str = "") -> None:
    for u in db.query("SELECT id FROM users WHERE role = ?", (role,)):
        notify(u["id"], text, link)
