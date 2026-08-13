"""
Общий приём загружаемого файла для раздела «База знаний».

Хранилище адресуется содержимым: имя файла — sha256 загруженных байтов, каталог
шардируется по первым двум парам hex-символов. Отсюда два свойства, на которые
опирается всё остальное: одинаковые файлы не дублируются на диске, а содержимое
по конкретному пути никогда не меняется — поэтому ETag можно ставить
неизменяемый.

Модуль ничего не знает ни про картинки, ни про документы: он принимает поток,
считает хеш, проверяет размер и кладёт файл на место. Чем именно является
принятое — решает `probe`, переданный вызывающим. Картинки проверяют себя через
Pillow (`images.py`), файлы — по расширению и сигнатуре (`file_types.py`).

Вынесено сюда, а не продублировано: разойдись две копии — получим разное
поведение при переполнении диска и при обрыве загрузки, то есть ровно в тех
случаях, которые никто не проверяет руками.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from django.conf import settings

_CHUNK = 64 * 1024


class UploadRejected(ValueError):
    """Содержимое не подошло — вьюха отдаёт 415."""


class UploadTooLarge(ValueError):
    """Файл больше лимита — вьюха отдаёт 413."""


@dataclass(frozen=True)
class StoredBlob:
    """Принятый файл: где лежит, чем является, сколько весит."""

    sha256: str
    relative_path: str
    mime: str
    byte_size: int
    # Что вернул probe сверх mime и расширения: картинки кладут сюда размеры.
    extra: dict


def media_root() -> Path:
    return Path(settings.KNOWLEDGE_MEDIA_ROOT)


def absolute_path(rel_path: str) -> Path:
    return media_root() / rel_path


def sharded_path(prefix: str, sha256: str, ext: str) -> str:
    """<prefix>/ab/cd/<sha256>.<ext> — два уровня шардирования по hex."""
    return f'{prefix}/{sha256[0:2]}/{sha256[2:4]}/{sha256}.{ext}'


def store_upload(
    stream,
    *,
    prefix: str,
    max_bytes: int,
    probe: Callable[[str], tuple[str, str, dict]],
    original_name: Optional[str] = None,
) -> StoredBlob:
    """
    Принять файл: записать во временный, посчитать sha256 потоково, проверить
    содержимое, переложить на постоянное место.

    probe получает путь к временному файлу и возвращает `(mime, ext, extra)`.
    Бросить он должен UploadRejected — тогда файл не сохраняется.

    Размер проверяется ПО ХОДУ чтения, а не после: иначе, чтобы отказать в
    приёме гигабайта, пришлось бы сперва записать этот гигабайт на диск.
    """
    digest = hashlib.sha256()
    size = 0

    tmp_fd, tmp_name = tempfile.mkstemp(prefix='kb-upload-')
    try:
        with os.fdopen(tmp_fd, 'wb') as tmp:
            while True:
                chunk = stream.read(_CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise UploadTooLarge(
                        f'Файл больше {max_bytes // (1024 * 1024)} МБ.'
                    )
                digest.update(chunk)
                tmp.write(chunk)

        if size == 0:
            raise UploadRejected('Файл пустой.')

        mime, ext, extra = probe(tmp_name)
        sha256 = digest.hexdigest()
        rel = sharded_path(prefix, sha256, ext)
        target = absolute_path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Файл с таким содержимым мог быть загружен раньше — перезапись
        # безопасна, содержимое то же самое по построению.
        shutil.move(tmp_name, target)
        tmp_name = None
        return StoredBlob(
            sha256=sha256, relative_path=rel, mime=mime,
            byte_size=size, extra=extra,
        )
    finally:
        if tmp_name and os.path.exists(tmp_name):
            os.unlink(tmp_name)
