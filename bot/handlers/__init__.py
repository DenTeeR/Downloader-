from aiogram import Router

from . import admin, cookies, design, download, start


def setup_routers() -> Router:
    root = Router(name="root")
    # Order matters: the download router catches every remaining text message,
    # so admin conversations (design studio, cookies, broadcast) must come first.
    root.include_routers(start.router, admin.router, design.router, cookies.router,
                         download.router)
    return root
