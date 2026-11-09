from aiogram import Router

from . import admin, download, start


def setup_routers() -> Router:
    root = Router(name="root")
    # Order matters: the download router catches every remaining text message.
    root.include_routers(start.router, admin.router, download.router)
    return root
