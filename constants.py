PROFILE_VIEW_PREFIX = "profile:view:"

BANK_OPTIONS = {
    "alpha": "Альфа",
    "sber": "Сбер",
    "ozon": "Ozon",
}

QR_REQUEST_PREFIX = "qr:req:"
QR_BANK_SELECT_PREFIX = "qr:bank:"
QR_SELLER_BANK_PREFIX = "qr:seller:bank:"
QR_SELLER_READY_PREFIX = "qr:seller:ready:"
QR_SELLER_ATTACH_PREFIX = "qr:seller:attach:"
QR_BUYER_READY_PREFIX = "qr:buyer:ready:"
QR_VIEW_PREFIX = "qr:view:"
QR_BUYER_DONE_PREFIX = "qr:buyer:done:"
QR_SELLER_DONE_PREFIX = "qr:seller:done:"


def bank_label(key: str | None) -> str:
    if not key:
        return "—"
    return BANK_OPTIONS.get(key, key)
