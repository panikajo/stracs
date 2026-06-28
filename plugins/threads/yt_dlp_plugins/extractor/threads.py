import os
import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import (
    ExtractorError,
    decode_base_n,
    float_or_none,
    int_or_none,
    mimetype2ext,
    str_or_none,
    traverse_obj,
    unescapeHTML,
    url_or_none,
)


_SHORTCODE_ALPHABET = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'


def _shortcode_to_id(shortcode):
    return str(decode_base_n(shortcode, table=_SHORTCODE_ALPHABET))


def _clean_threads_url(url, username=None, shortcode=None):
    """Remove Slack wrappers/query params and return canonical Threads URL."""
    u = str(url or '').replace('&lt;', '<').replace('&gt;', '>').strip().strip('\'"').strip().strip('<>').strip()
    if u.startswith('http') and '|' in u:
        u = u.split('|', 1)[0].strip('<>').strip()
    m = re.search(r'https?://(?:www\.)?threads\.(?:net|com)/(?:@(?P<username>[^/?#>]+)/(?:post|media)/|t/)(?P<id>[A-Za-z0-9_-]+)', u, re.I)
    if m:
        username = username or m.group('username')
        shortcode = shortcode or m.group('id')
    if shortcode and username:
        return f'https://www.threads.net/@{username}/post/{shortcode}'
    if shortcode:
        return f'https://www.threads.net/t/{shortcode}'
    return u


class ThreadsIE(InfoExtractor):
    IE_NAME = 'threads'
    IE_DESC = 'Threads posts'
    _VALID_URL = r'https?://(?:www\.)?threads\.(?:net|com)/(?:@(?P<username>[^/?#]+)/post/|t/)(?P<id>[A-Za-z0-9_-]+)'

    _GRAPH_FIELDS = ','.join((
        'id',
        'media_product_type',
        'media_type',
        'media_url',
        'gif_url',
        'permalink',
        'owner',
        'username',
        'text',
        'timestamp',
        'shortcode',
        'thumbnail_url',
        'children{id,media_type,media_url,thumbnail_url,permalink,username,text,timestamp,shortcode}',
        'is_quote_post',
        'quoted_post{id,media_type,media_url,thumbnail_url,permalink,username,text,timestamp,shortcode}',
        'reposted_post{id,media_type,media_url,thumbnail_url,permalink,username,text,timestamp,shortcode}',
        'alt_text',
    ))

    _TESTS = [{
        'url': 'https://www.threads.com/@dream.in.sanity/post/DZLiOyeklke',
        'only_matching': True,
    }, {
        'url': 'https://www.threads.net/t/DZLiOyeklke',
        'only_matching': True,
    }]

    def _access_token(self):
        return (
            self._configuration_arg('access_token', [None])[0]
            or os.environ.get('THREADS_ACCESS_TOKEN'))

    def _extract_graph_post(self, shortcode):
        token = self._access_token()
        if not token:
            return None

        post_id = _shortcode_to_id(shortcode)
        return self._download_json(
            f'https://graph.threads.net/v1.0/{post_id}', shortcode,
            note='Downloading Threads Graph API post data',
            query={
                'fields': self._GRAPH_FIELDS,
                'access_token': token,
            }, fatal=False)

    def _iter_dicts(self, value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from self._iter_dicts(child)
        elif isinstance(value, list):
            for child in value:
                yield from self._iter_dicts(child)

    def _media_entry_from_api_post(self, post, fallback_id):
        media_url = url_or_none(post.get('media_url') or post.get('gif_url'))
        thumbnail = url_or_none(post.get('thumbnail_url'))
        if not media_url:
            return None

        media_type = str_or_none(post.get('media_type'))
        info = {
            'id': str_or_none(post.get('shortcode') or post.get('id')) or fallback_id,
            'url': media_url,
            'title': str_or_none(post.get('text')) or f'Threads post {fallback_id}',
            'description': str_or_none(post.get('text') or post.get('alt_text')),
            'thumbnail': thumbnail,
            'timestamp': int_or_none(post.get('timestamp')),
            'uploader': str_or_none(post.get('username')),
            'webpage_url': url_or_none(post.get('permalink')),
        }
        if media_type:
            info['format_id'] = media_type.lower()
        return info

    def _extract_from_graph(self, post, shortcode):
        entries = []

        for candidate in (post, *(post.get('children') or []), post.get('quoted_post'), post.get('reposted_post')):
            if isinstance(candidate, dict):
                entry = self._media_entry_from_api_post(candidate, shortcode)
                if entry:
                    entries.append(entry)

        if len(entries) == 1:
            return entries[0]
        if entries:
            return {
                '_type': 'playlist',
                'id': shortcode,
                'title': str_or_none(post.get('text')) or f'Threads post {shortcode}',
                'description': str_or_none(post.get('text')),
                'uploader': str_or_none(post.get('username')),
                'entries': entries,
            }
        return None

    def _extract_media_object(self, media, media_id):
        user = media.get('user') or {}
        description = traverse_obj(media, ('caption', 'text'), expected_type=str_or_none)
        thumbnails = [{
            'url': url_or_none(candidate.get('url')),
            'width': int_or_none(candidate.get('width')),
            'height': int_or_none(candidate.get('height')),
        } for candidate in traverse_obj(media, ('image_versions2', 'candidates')) or []]
        thumbnails = [thumbnail for thumbnail in thumbnails if thumbnail.get('url')]

        formats = []
        for fmt in media.get('video_versions') or []:
            if not isinstance(fmt, dict):
                continue
            fmt_url = url_or_none(fmt.get('url'))
            if not fmt_url:
                continue
            formats.append({
                'format_id': str_or_none(fmt.get('id') or fmt.get('type')),
                'url': fmt_url,
                'width': int_or_none(fmt.get('width')),
                'height': int_or_none(fmt.get('height')),
                'vcodec': media.get('video_codec'),
            })

        for key in ('video_url', 'playable_url', 'media_url', 'gif_url'):
            fmt_url = url_or_none(media.get(key))
            if fmt_url and not any(fmt['url'] == fmt_url for fmt in formats):
                formats.append({'url': fmt_url})

        info = {
            'id': str_or_none(media.get('code') or media.get('pk') or media.get('id')) or media_id,
            'title': description or f'Threads post {media_id}',
            'description': description,
            'duration': float_or_none(media.get('video_duration') or media.get('duration')),
            'timestamp': int_or_none(media.get('taken_at') or media.get('taken_at_timestamp')),
            'uploader': str_or_none(user.get('username')),
            'uploader_id': str_or_none(user.get('pk') or user.get('id')),
            'thumbnails': thumbnails,
            'view_count': int_or_none(media.get('view_count')),
            'like_count': int_or_none(media.get('like_count')),
            'comment_count': int_or_none(media.get('comment_count')),
        }

        if formats:
            return {
                **info,
                'formats': formats,
                'http_headers': {'Referer': 'https://www.threads.net/'},
            }

        if thumbnails:
            image = max(thumbnails, key=lambda thumbnail: (
                (thumbnail.get('width') or 0) * (thumbnail.get('height') or 0),
                thumbnail.get('width') or 0,
                thumbnail.get('height') or 0))
            return {
                **info,
                'url': image['url'],
                'width': image.get('width'),
                'height': image.get('height'),
                'http_headers': {'Referer': 'https://www.threads.net/'},
            }

        return None


    def _extract_meta_fallback(self, webpage, shortcode):
        """Last-resort extraction from OpenGraph/meta or raw escaped media URLs."""
        entries = []
        seen = set()

        def add(media_url, kind=None):
            media_url = url_or_none((media_url or '').replace('\\/', '/').replace('&amp;', '&'))
            if not media_url or media_url in seen:
                return
            # Avoid app icons/sprites/profile pictures. Raw image URLs in the
            # shell are often app assets, not post media; video URLs are safer.
            if 'static.cdninstagram.com' in media_url:
                return
            if 't51.82787-19' in media_url or 'profile_pic' in media_url:
                return
            seen.add(media_url)
            entry = {
                'id': f'{shortcode}-{len(entries) + 1}',
                'url': media_url,
                'title': f'Threads post {shortcode}',
                'http_headers': {'Referer': 'https://www.threads.net/'},
            }
            if kind:
                entry['format_id'] = kind
            entries.append(entry)

        for pattern in (
                r'<meta[^>]+property=["\']og:video(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:video(?::secure_url)?["\']',
                r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image(?::secure_url)?["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)',
        ):
            for media_url in re.findall(pattern, webpage, flags=re.I):
                add(unescapeHTML(media_url), 'meta')

        # Raw media URLs can be embedded escaped in Relay payloads.
        for media_url in re.findall(r'https?:\\?/\\?/[^"\'<>\\\s]+?\.(?:mp4|m3u8)(?:\?[^"\'<>\\\s]+)?', webpage, flags=re.I):
            add(media_url, 'raw')

        if len(entries) == 1:
            return entries[0]
        if entries:
            return {
                '_type': 'playlist',
                'id': shortcode,
                'title': f'Threads post {shortcode}',
                'entries': entries,
            }
        return None


    def _looks_like_profile_or_asset(self, entry):
        """Reject common non-post images from Threads shell/profile UI."""
        urls = []
        if isinstance(entry, dict):
            if entry.get('url'):
                urls.append(str(entry.get('url')))
            for thumb in entry.get('thumbnails') or []:
                if isinstance(thumb, dict) and thumb.get('url'):
                    urls.append(str(thumb.get('url')))
        joined = ' '.join(urls)
        if not joined:
            return False
        bad_markers = (
            'static.cdninstagram.com/rsrc.php',
            'profile_pic',
            't51.82787-19',  # common Instagram/Threads profile picture path
            's150x150',
        )
        return any(marker in joined for marker in bad_markers)

    def _extract_broad_relay_media(self, webpage, shortcode):
        """Fallback for current Threads Relay payloads.

        Some Threads pages keep the requested shortcode in one Relay object and the
        media candidates in nearby/nested objects without repeating `code` on the
        exact dict that contains `video_versions` / `image_versions2`. The original
        extractor therefore sees the shortcode but misses the actual media. This
        fallback walks all JSON payloads, extracts every media-looking object, and
        filters obvious app assets/profile images.
        """
        entries = []
        seen = set()

        def add_entry(media):
            entry = self._extract_media_object(media, f'{shortcode}-{len(entries) + 1}')
            if not entry or self._looks_like_profile_or_asset(entry):
                return
            # Avoid duplicates by first direct URL/format URL/thumb URL.
            urls = []
            if entry.get('url'):
                urls.append(entry.get('url'))
            for fmt in entry.get('formats') or []:
                if isinstance(fmt, dict) and fmt.get('url'):
                    urls.append(fmt.get('url'))
            for thumb in entry.get('thumbnails') or []:
                if isinstance(thumb, dict) and thumb.get('url'):
                    urls.append(thumb.get('url'))
            key = next((u for u in urls if u), None) or str(media.get('id') or media.get('pk') or len(entries))
            if key in seen:
                return
            seen.add(key)
            entries.append(entry)

        def media_score(item):
            if not isinstance(item, dict):
                return 0
            score = 0
            if item.get('video_versions'):
                score += 10
            candidates = traverse_obj(item, ('image_versions2', 'candidates')) or []
            if candidates:
                score += 5
                # prefer non-profile, larger images
                max_area = 0
                for c in candidates:
                    if isinstance(c, dict):
                        max_area = max(max_area, (int_or_none(c.get('width')) or 0) * (int_or_none(c.get('height')) or 0))
                if max_area >= 250000:
                    score += 3
            if item.get('carousel_media'):
                score += 4
            return score

        # Parse JSON-LD and application/json payloads.
        json_objects = []
        for obj in self._yield_json_ld(webpage, shortcode, fatal=False) or []:
            json_objects.append(obj)
        for mobj in re.finditer(
                r'<script[^>]+type=["\']application/json["\'][^>]*>(?P<json>.*?)</script>',
                webpage, flags=re.DOTALL):
            script_json = self._parse_json(unescapeHTML(mobj.group('json')), shortcode, fatal=False)
            if script_json:
                json_objects.append(script_json)

        media_candidates = []
        for obj in json_objects:
            for item in self._iter_dicts(obj):
                if not isinstance(item, dict):
                    continue
                if item.get('carousel_media'):
                    for child in item.get('carousel_media') or []:
                        if media_score(child):
                            media_candidates.append(child)
                if media_score(item):
                    media_candidates.append(item)

        # Higher score first: videos, large post images before profile/thumbs.
        media_candidates.sort(key=media_score, reverse=True)
        for media in media_candidates:
            add_entry(media)

        if len(entries) == 1:
            return entries[0]
        if entries:
            return {
                '_type': 'playlist',
                'id': shortcode,
                'title': f'Threads post {shortcode}',
                'entries': entries,
            }
        return None

    def _extract_public_media(self, webpage, shortcode):
        target_id = _shortcode_to_id(shortcode)
        target_media = []
        target_seen = set()
        fallback_entries = []
        fallback_seen = set()

        def add_fallback_url(media_url, media=None):
            media_url = url_or_none(media_url)
            if not media_url or media_url in fallback_seen:
                return
            fallback_seen.add(media_url)
            media = media or {}
            ext = mimetype2ext(media.get('mime_type')) or None
            fallback_entries.append({
                'id': f'{shortcode}-{len(fallback_entries) + 1}',
                'url': media_url,
                'title': f'Threads post {shortcode}',
                'ext': ext,
                'width': int_or_none(media.get('width')),
                'height': int_or_none(media.get('height')),
                'duration': int_or_none(media.get('duration')),
                'thumbnail': traverse_obj(media, (
                    ('thumbnail_url', 'display_url'),
                    {url_or_none}, any)),
            })

        def collect_target_media(obj):
            for item in self._iter_dicts(obj):
                item_id = str_or_none(item.get('pk') or item.get('id'))
                if (
                        item.get('code') == shortcode
                        or item_id == target_id
                        or (item_id and item_id.startswith(f'{target_id}_'))):
                    target_key = item.get('code') or item_id
                    if target_key and target_key not in target_seen:
                        target_seen.add(target_key)
                        target_media.append(item)

        for media_url in re.findall(r'https?:\\?/\\?/[^"\'<>\\\s]+?\.(?:mp4|m3u8)(?:\?[^"\'<>\\\s]+)?', webpage):
            add_fallback_url(media_url.replace('\\/', '/'))

        for obj in self._yield_json_ld(webpage, shortcode, fatal=False) or []:
            collect_target_media(obj)

        for mobj in re.finditer(
                r'<script[^>]+type=["\']application/json["\'][^>]*>(?P<json>.*?)</script>',
                webpage, flags=re.DOTALL):
            script_json = self._parse_json(unescapeHTML(mobj.group('json')), shortcode, fatal=False)
            if script_json:
                collect_target_media(script_json)

        entries = []
        for media in target_media:
            carousel_media = media.get('carousel_media')
            if carousel_media:
                for idx, child_media in enumerate(carousel_media, start=1):
                    entry = self._extract_media_object(child_media, f'{shortcode}-{idx}')
                    if entry:
                        entries.append(entry)
                continue
            entry = self._extract_media_object(media, shortcode)
            if entry:
                entries.append(entry)

        if not entries:
            entries = fallback_entries

        if not entries:
            return None

        if len(entries) == 1:
            return entries[0]
        return {
            '_type': 'playlist',
            'id': shortcode,
            'title': f'Threads post {shortcode}',
            'entries': entries,
        }

    def _real_extract(self, url):
        mobj = self._match_valid_url(url)
        shortcode = mobj.group('id')
        username = mobj.group('username')
        url = _clean_threads_url(url, username=username, shortcode=shortcode)

        graph_post = self._extract_graph_post(shortcode)
        if graph_post:
            graph_result = self._extract_from_graph(graph_post, shortcode)
            if graph_result:
                return graph_result

        webpage = self._download_webpage(
            url, shortcode, fatal=False, headers={
                'User-Agent': self.get_param('http_headers', {}).get(
                    'User-Agent',
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                    '(KHTML, like Gecko) Chrome/125 Safari/537.36'),
            })
        if webpage:
            public_result = self._extract_public_media(webpage, shortcode)
            if public_result:
                public_result.setdefault('uploader', username)
                return public_result
            broad_result = self._extract_broad_relay_media(webpage, shortcode)
            if broad_result:
                if isinstance(broad_result, dict):
                    broad_result.setdefault('uploader', username)
                return broad_result
            meta_result = self._extract_meta_fallback(webpage, shortcode)
            if meta_result:
                if isinstance(meta_result, dict):
                    meta_result.setdefault('uploader', username)
                return meta_result

        raise ExtractorError(
            'Unable to find downloadable Threads media in the public page. '
            'If this post is public but the page shell omits media data, pass a Threads Graph API '
            'token with --extractor-args "threads:access_token=TOKEN" or THREADS_ACCESS_TOKEN.',
            expected=True)
