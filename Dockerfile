# syntax=docker/dockerfile:1
# Reverse-Wordle-Solver – schlankes Alpine-Image, nur Standardbibliothek.
FROM python:3.12-alpine

# UTF-8 für Emoji-Grids und Umlaute, ungepufferte Ausgabe für flüssiges TUI.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8

WORKDIR /app

# Nur das Nötige: Code, Tests und die offiziellen Wortlisten.
COPY data ./data
COPY wordle ./wordle
COPY tests ./tests
COPY reverse_wordle.py ./

# Das TUI braucht ein Terminal, aber keine root-Rechte.
RUN adduser -D -s /bin/sh solver
USER solver

# TUI:      docker run -it --rm wordle-reverse-solver
# Batch:    docker run -it --rm wordle-reverse-solver -s crane -r GYXXG
ENTRYPOINT ["python3", "reverse_wordle.py"]
