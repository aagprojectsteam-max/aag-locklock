# ADR 0005: Windows tray and cursor

Status: tray retained; global cursor hiding unsupported in beta.2.

Tray callbacks enqueue work for the Tk main thread. Controller notifications run outside the outermost controller lock, including nested idle-policy actions. A serialized worker handles power-service communication.

The previous ShowCursor worker changed only its own thread display count and could not guarantee global visibility behavior. It has been removed. Settings advertise the capability as unsupported, reject enabling it and migrate old enabled settings off. No cursor scheme replacement is used.
