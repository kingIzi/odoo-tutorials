def show_display_notification(title, message, type="success", sticky=False):
    return {
        "type": "ir.actions.client",
        "tag": "display_notification",
        "params": {
            "title": title,
            "message": message,
            "type": type,
            "sticky": sticky,
        },
    }
