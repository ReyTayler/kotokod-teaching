"""Тесты файлового слоя картинок: пути, хеш, приём файла, оптимизация, API."""
from __future__ import annotations

import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from PIL import Image

from apps.knowledge import images


def _png_bytes(width: int = 20, height: int = 10, color=(255, 0, 0)) -> bytes:
    buf = io.BytesIO()
    Image.new('RGB', (width, height), color).save(buf, format='PNG')
    return buf.getvalue()


# --- пути ------------------------------------------------------------------

def test_relative_path_shards_by_first_hex_pairs():
    path = images.relative_path('abcdef' + '0' * 58, 'png')
    assert path == 'knowledge/ab/cd/' + 'abcdef' + '0' * 58 + '.png'


def test_variant_path_appends_suffix():
    sha = 'ab' + '0' * 62
    assert images.variant_path(sha, 'w400') == f'knowledge/ab/00/{sha}.w400.webp'


# --- приём файла -----------------------------------------------------------

def test_store_upload_writes_file_and_returns_metadata(tmp_path):
    payload = _png_bytes(30, 15)
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        meta = images.store_upload(io.BytesIO(payload), 'скрин.png')

    assert meta.mime == 'image/png'
    assert meta.width == 30 and meta.height == 15
    assert meta.byte_size == len(payload)
    assert len(meta.sha256) == 64
    assert (tmp_path / meta.relative_path).exists()


def test_store_upload_is_deterministic_by_content(tmp_path):
    payload = _png_bytes()
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        first = images.store_upload(io.BytesIO(payload), 'a.png')
        second = images.store_upload(io.BytesIO(payload), 'b.png')
    assert first.sha256 == second.sha256


def test_store_upload_rejects_non_image(tmp_path):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        with pytest.raises(images.ImageRejected, match='формат'):
            images.store_upload(io.BytesIO(b'not an image at all'), 'x.png')


def test_store_upload_rejects_svg(tmp_path):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        with pytest.raises(images.ImageRejected, match='формат'):
            images.store_upload(io.BytesIO(svg), 'x.svg')


def test_store_upload_rejects_oversized(tmp_path):
    payload = _png_bytes()
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path), KNOWLEDGE_MAX_IMAGE_BYTES=10):
        with pytest.raises(images.ImageTooLarge):
            images.store_upload(io.BytesIO(payload), 'x.png')


# --- оптимизация -----------------------------------------------------------

def test_build_variants_creates_webp_files(tmp_path):
    payload = _png_bytes(2000, 1000)
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        meta = images.store_upload(io.BytesIO(payload), 'big.png')
        result = images.build_variants(meta.sha256, meta.relative_path)

    optimized = tmp_path / result.optimized_path
    thumb = tmp_path / result.thumb_path
    assert optimized.exists() and thumb.exists()
    with Image.open(optimized) as im:
        assert im.width == 1600          # ужато по длинной стороне
        assert im.format == 'WEBP'
    with Image.open(thumb) as im:
        assert im.width == 400


def test_build_variants_strips_exif(tmp_path):
    buf = io.BytesIO()
    im = Image.new('RGB', (100, 50), (0, 128, 0))
    exif = im.getexif()
    exif[271] = 'TestCamera'             # Make
    im.save(buf, format='JPEG', exif=exif)

    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        meta = images.store_upload(io.BytesIO(buf.getvalue()), 'photo.jpg')
        result = images.build_variants(meta.sha256, meta.relative_path)

    with Image.open(tmp_path / result.optimized_path) as out:
        assert dict(out.getexif()) == {}


# ---------------------------------------------------------------------------
# API загрузки и отдачи
# ---------------------------------------------------------------------------

IMAGES = '/api/admin/knowledge/images'
DOCS = '/api/admin/knowledge/documents'
SECTIONS = '/api/admin/knowledge/sections'


def _upload(client, tmp_path, name='__test_kb_a.png', payload=None):
    file = SimpleUploadedFile(name, payload or _png_bytes(), content_type='image/png')
    return client.post(IMAGES, {'file': file}, format='multipart')


@pytest.mark.django_db
def test_upload_returns_pending_image(admin_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        resp = _upload(admin_client, tmp_path)
    assert resp.status_code == 201
    body = resp.json()
    assert body['optimize_state'] in ('pending', 'ready')
    assert body['width'] == 20 and body['height'] == 10


@pytest.mark.django_db
def test_upload_deduplicates_by_content(admin_client, tmp_path, kb_clean):
    payload = _png_bytes(33, 22)
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        first = _upload(admin_client, tmp_path, '__test_kb_1.png', payload).json()
        second = _upload(admin_client, tmp_path, '__test_kb_2.png', payload).json()
    assert first['id'] == second['id']


@pytest.mark.django_db
def test_manager_cannot_upload(manager_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        assert _upload(manager_client, tmp_path).status_code == 403


@pytest.mark.django_db
def test_upload_rejects_svg(admin_client, tmp_path, kb_clean):
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    file = SimpleUploadedFile('__test_kb_x.svg', svg, content_type='image/svg+xml')
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        resp = admin_client.post(IMAGES, {'file': file}, format='multipart')
    assert resp.status_code == 415


@pytest.mark.django_db
def test_upload_rejects_oversized(admin_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path), KNOWLEDGE_MAX_IMAGE_BYTES=10):
        resp = _upload(admin_client, tmp_path)
    assert resp.status_code == 413


@pytest.mark.django_db
def test_serve_uses_x_accel_redirect(admin_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        section = admin_client.post(
            SECTIONS, {'title': '__test_kb_раздел'}, format='json',
        ).json()
        doc = admin_client.post(
            DOCS, {'section_id': section['id'], 'title': '__test_kb_док'}, format='json',
        ).json()
        admin_client.patch(
            f"{DOCS}/{doc['id']}",
            {'content': {'type': 'doc', 'content': [
                {'type': 'knowledgeImage', 'attrs': {'imageId': image['id']}},
            ]}},
            format='json',
        )
        with override_settings(KNOWLEDGE_X_ACCEL_PREFIX='/internal-media'):
            resp = admin_client.get(f"{IMAGES}/{image['id']}")

    assert resp.status_code == 200
    assert resp['X-Accel-Redirect'].startswith('/internal-media/knowledge/')
    assert resp.content == b''          # байты отдаёт nginx, не Python


@pytest.mark.django_db
def test_serve_denied_when_no_visible_document(
    admin_client, teacher_client, tmp_path, kb_clean,
):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        section = admin_client.post(
            SECTIONS, {'title': '__test_kb_раздел'}, format='json',
        ).json()
        doc = admin_client.post(
            DOCS, {'section_id': section['id'], 'title': '__test_kb_док'}, format='json',
        ).json()
        admin_client.patch(
            f"{DOCS}/{doc['id']}",
            {'content': {'type': 'doc', 'content': [
                {'type': 'knowledgeImage', 'attrs': {'imageId': image['id']}},
            ]}},
            format='json',
        )
        # Документ остался черновиком без ролей → преподавателю картинка не видна.
        resp = teacher_client.get(f"{IMAGES}/{image['id']}")

    assert resp.status_code == 404


@pytest.mark.django_db
def test_serve_falls_back_to_original_when_not_optimized(
    admin_client, tmp_path, kb_clean,
):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_images SET optimize_state='pending',"
                ' optimized_path=NULL WHERE id = %s', [image['id']],
            )
        section = admin_client.post(
            SECTIONS, {'title': '__test_kb_раздел'}, format='json',
        ).json()
        doc = admin_client.post(
            DOCS, {'section_id': section['id'], 'title': '__test_kb_док'}, format='json',
        ).json()
        admin_client.patch(
            f"{DOCS}/{doc['id']}",
            {'content': {'type': 'doc', 'content': [
                {'type': 'knowledgeImage', 'attrs': {'imageId': image['id']}},
            ]}},
            format='json',
        )
        with override_settings(KNOWLEDGE_X_ACCEL_PREFIX='/internal-media'):
            resp = admin_client.get(f"{IMAGES}/{image['id']}?variant=optimized")

    assert resp.status_code == 200
    # Отдан оригинал: путь заканчивается на .png, а не на .webp
    assert resp['X-Accel-Redirect'].endswith('.png')
    # Фолбэк живёт до готовности WebP — сутки его кэшировать нельзя.
    assert resp['Cache-Control'] == 'private, max-age=60'


@pytest.mark.django_db
def test_etag_differs_between_fallback_and_ready_variant(
    admin_client, tmp_path, kb_clean,
):
    """
    ETag обязан меняться, когда по тому же адресу поехали другие байты.

    ?variant=optimized сначала отдаёт оригинал, а после Celery — WebP. С ETag
    из одного лишь хеша оригинала браузер на проверке получал бы «не
    изменилось» и оставался с тяжёлым PNG навсегда.
    """
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_images SET optimize_state='pending',"
                ' optimized_path=NULL WHERE id = %s', [image['id']],
            )
        fallback = admin_client.get(f"{IMAGES}/{image['id']}?variant=optimized")

        variants = images.build_variants(
            *_sha_and_path(image['id']),
        )
        with connection.cursor() as cur:
            cur.execute(
                "UPDATE knowledge_images SET optimize_state='ready',"
                ' optimized_path=%s WHERE id = %s',
                [variants.optimized_path, image['id']],
            )
        ready = admin_client.get(f"{IMAGES}/{image['id']}?variant=optimized")

    assert fallback.status_code == ready.status_code == 200
    assert fallback['ETag'] != ready['ETag']
    assert ready['Cache-Control'] == 'private, max-age=86400'


def _sha_and_path(image_id: int) -> tuple[str, str]:
    with connection.cursor() as cur:
        cur.execute(
            'SELECT sha256, original_path FROM knowledge_images WHERE id = %s',
            [image_id],
        )
        return cur.fetchone()


@pytest.mark.django_db
def test_serve_rejects_unknown_variant(admin_client, tmp_path, kb_clean):
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        resp = admin_client.get(f"{IMAGES}/{image['id']}?variant=huge")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Лимит пикселей, уборка сирот, доступ автора к ещё не сохранённой картинке
# ---------------------------------------------------------------------------

def test_store_upload_rejects_pixel_bomb(tmp_path):
    # Файл может быть крошечным по байтам и огромным по пикселям — на VPS с
    # 2 ГБ RAM его разворачивание кладёт весь сервер.
    payload = _png_bytes(4000, 4000)
    with override_settings(
        KNOWLEDGE_MEDIA_ROOT=str(tmp_path), KNOWLEDGE_MAX_IMAGE_PIXELS=1000,
    ):
        with pytest.raises(images.ImageTooLarge):
            images.store_upload(io.BytesIO(payload), 'bomb.png')


@pytest.mark.django_db
def test_admin_sees_image_before_it_is_saved_into_document(admin_client, tmp_path, kb_clean):
    """Свежезагруженная картинка ещё не привязана к документу — но видна автору.

    Иначе только что вставленный в редактор скриншот показывался бы битым до
    первого сохранения.
    """
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        resp = admin_client.get(f"{IMAGES}/{image['id']}")
    assert resp.status_code == 200


@pytest.mark.django_db
def test_teacher_cannot_see_unused_image(teacher_client, admin_client, tmp_path, kb_clean):
    """Послабление действует только для тех, кто и так видит все документы."""
    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        resp = teacher_client.get(f"{IMAGES}/{image['id']}")
    assert resp.status_code == 404


@pytest.mark.django_db
def test_orphan_ignores_images_used_by_live_documents(admin_client, tmp_path, kb_clean):
    from datetime import timedelta

    from django.utils import timezone

    from apps.knowledge import repository

    with override_settings(KNOWLEDGE_MEDIA_ROOT=str(tmp_path)):
        image = _upload(admin_client, tmp_path).json()
        section = admin_client.post(
            SECTIONS, {'title': '__test_kb_раздел'}, format='json',
        ).json()
        doc = admin_client.post(
            DOCS, {'section_id': section['id'], 'title': '__test_kb_док'}, format='json',
        ).json()
        admin_client.patch(
            f"{DOCS}/{doc['id']}",
            {'content': {'type': 'doc', 'content': [
                {'type': 'knowledgeImage', 'attrs': {'imageId': image['id']}},
            ]}},
            format='json',
        )
        future = timezone.now() + timedelta(days=1)
        assert image['id'] not in repository.orphan_image_ids(future)

        # Документ удаляют мягко — использование остаётся строкой в БД, но
        # картинка обязана стать кандидатом на уборку, иначе файлы копятся вечно.
        admin_client.delete(f"{DOCS}/{doc['id']}")
        assert image['id'] in repository.orphan_image_ids(future)
