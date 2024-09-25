import asyncio
import io
import math
import random
from asyncio import Semaphore
from collections.abc import Awaitable, Iterator, Sequence
from statistics import mean
from time import time

import logfire
from httpx import AsyncClient
from PIL import Image, ImageDraw

__all__ = ('BuildMap',)

SHARDS = 'a', 'b', 'c'
TILE_SIZE = 256
HEADERS = {'User-Agent': 'https://github.com/tutorcruncher/static-maps'}

COPYRIGHT_MSG = '© OpenStreetMap contributors'

OSM_ROOT = 'https://{shard}.tile.openstreetmap.org'

URL_TEMPLATE = '{url_root}/{zoom:d}/{x:d}/{y:d}.png'
OSM_SEMAPHORE = Semaphore(value=32)


class BuildMap:
    __slots__ = 'http_client', 'lat', 'lng', 'zoom', 'w', 'h', 'no_tiles', 'tiles', 'times', 'headers', 'scale'

    def __init__(
        self,
        *,
        http_client: AsyncClient,
        referrer: str | None,
        lat: float,
        lng: float,
        zoom: int,
        width: int,
        height: int,
        scale: int,
    ):
        self.http_client = http_client
        self.lat = lat
        self.lng = lng
        self.zoom = zoom
        self.w = width * scale
        self.h = height * scale
        self.scale = scale
        self.no_tiles = 2**self.zoom

        self.tiles: set[tuple[bytes, int, int]] = set()
        self.times: list[float] = []
        self.headers = HEADERS.copy()
        if referrer:
            self.headers['Referer'] = referrer

    async def run(self) -> bytes:
        # https://wiki.openstreetmap.org/wiki/Slippy_map_tilenames#Implementations
        x_tile = self.no_tiles * (self.lng + 180) / 360

        lat_rad = math.radians(self.lat)
        y_tile = self.no_tiles * (1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2

        x_range, x_correction = self.range_correction(x_tile, self.w)
        y_range, y_correction = self.range_correction(y_tile, self.h)

        await asyncio.gather(*self.get_tiles(x_range, x_correction, y_range, y_correction))

        logfire.info(
            '{lat=:0.6f} {lng=:0.6f} {zoom=} {tiles=} {avg_download_time=:0.3f}s',
            lat=self.lat,
            lng=self.lng,
            zoom=self.zoom,
            tiles=len(self.times),
            avg_download_time=mean(self.times),
            times=self.times,
        )

        return await asyncio.get_event_loop().run_in_executor(None, self.stitch_tiles)

    @staticmethod
    def range_correction(tile_no: float, size: int) -> tuple[Sequence[int], int]:
        half_t = size / 2 / TILE_SIZE  # half the width/height in tiles
        min_, max_ = int(math.floor(tile_no - half_t)), int(math.ceil(tile_no + half_t))
        correction = (tile_no - min_) * TILE_SIZE - size / 2
        return range(min_, max_), intr(correction)

    def get_tiles(
        self, x_range: Sequence[int], x_correction: int, y_range: Sequence[int], y_correction: int
    ) -> Iterator[Awaitable[None]]:
        for col, x in enumerate(x_range):
            for row, y in enumerate(y_range):
                yield self.get_tile(x, y, col * TILE_SIZE - x_correction, row * TILE_SIZE - y_correction)

    async def get_tile(self, osm_x: int, osm_y: int, image_x: int, image_y: int) -> None:
        if not 0 <= osm_y < self.no_tiles:
            return
        # wraps map around at edges
        osm_x = osm_x % self.no_tiles
        root = OSM_ROOT.format(shard=random.choice(SHARDS))
        url = URL_TEMPLATE.format(url_root=root, zoom=self.zoom, x=osm_x, y=osm_y)
        # debug(url, osm_x, osm_y, image_x, image_y)

        start = time()
        async with OSM_SEMAPHORE:
            r = await self.http_client.get(url, headers=self.headers)
        self.times.append(time() - start)
        if r.status_code != 200:
            data = {'content': r.content, 'response_headers': dict(r.headers)}
            logfire.warn('unexpected {status=} from {url!r}', status=r.status_code, url=url, data=data)
        else:
            self.tiles.add((r.content, image_x, image_y))

    @logfire.instrument('stitch tiles together')
    def stitch_tiles(self) -> bytes:
        # the minimum image width is set to 95px to fit copyright text
        box_size_w, box_size_h = 95, 8
        text_pos_x, text_pos_y = 94, 8
        if self.w >= 205:
            box_size_w, box_size_h = 205, 20
            text_pos_x, text_pos_y = 200, 20

        img_bg = Image.new('RGBA', (self.w, self.h), (255, 255, 255, 255))

        for content, x, y in self.tiles:
            img_bg.paste(Image.open(io.BytesIO(content)), (x, y))

        self.tiles = set()
        img_fg = Image.new('RGBA', img_bg.size, (0, 0, 0, 0))
        rect_box = self.w - box_size_w * self.scale, self.h - box_size_h * self.scale, self.w, self.h
        ImageDraw.Draw(img_fg).rectangle(rect_box, fill=(255, 255, 255, 128))
        text_pos: tuple[int, int] = self.w - text_pos_x * self.scale, self.h - text_pos_y * self.scale
        ImageDraw.Draw(img_fg).text(text_pos, COPYRIGHT_MSG, fill=(0, 0, 0))  # type: ignore

        bio = io.BytesIO()
        Image.alpha_composite(img_bg, img_fg).convert('RGB').save(bio, format='jpeg', quality=95, optimize=True)
        return bio.getvalue()


def intr(v: float) -> int:
    return int(round(v))
