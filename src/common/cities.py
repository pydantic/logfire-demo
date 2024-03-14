from collections import defaultdict
from pathlib import Path
from typing import Annotated

import logfire
from logfire.integrations.pydantic_plugin import PluginSettings
from httpx import AsyncClient
from pydantic import BaseModel, Field, TypeAdapter, BeforeValidator, ConfigDict
from asyncpg import Connection

config_record = ConfigDict(plugin_settings=PluginSettings(logfire={'record': 'all'}))


class City(BaseModel):
    model_config = config_record
    id: int = Field(title='ID')
    city: str = Field(title='Name')
    city_ascii: str = Field(title='City Ascii')
    lat: float = Field(title='Latitude')
    lng: float = Field(title='Longitude')
    country: str = Field(title='Country')
    iso2: str = Field(title='ISO2')
    iso3: str = Field(title='ISO3')
    admin_name: str | None = Field(title='Admin Name')
    capital: str | None = Field(title='Capital')
    population: int = Field(title='Population')


# cities_adapter = TypeAdapter(list[Annotated[City, BeforeValidator(dict)]], config=config_record)
cities_adapter = TypeAdapter(list[Annotated[City, BeforeValidator(dict)]])
PAGE_LIMIT = 50


async def list_cities(conn: Connection, offset: int) -> tuple[list[City], int]:
    rows = await conn.fetch('SELECT * FROM cities ORDER BY population desc OFFSET $1 LIMIT 50', offset)
    cities = cities_adapter.validate_python(rows)
    total = await conn.fetchval('SELECT COUNT(*) FROM cities')
    return cities, total


async def filter_cities(conn: Connection, iso3: str, offset: int) -> tuple[list[City], int]:
    rows = await conn.fetch('SELECT * FROM cities WHERE iso3=$1 ORDER BY population desc OFFSET $2 LIMIT 50', iso3, offset)
    cities = cities_adapter.validate_python(rows)
    total = await conn.fetchval('SELECT COUNT(*) FROM cities WHERE iso3=$1', iso3)
    return cities, total


async def search_name(client: AsyncClient, name: str) -> list[dict[str, str]]:
    url = f'https://restcountries.com/v3.1/{f'name/{name}' if name else 'all'}'
    with logfire.span('GET {url=}', url=url):
        r = await client.get(url)
    if r.status_code == 404:
        return []
    else:
        r.raise_for_status()
        data = r.json()
        if not name:
            # if we got all, filter to the 20 most populous countries
            data.sort(key=lambda x: x['population'], reverse=True)
            data = data[0:20]
            data.sort(key=lambda x: x['name']['common'])

        regions = defaultdict(list)
        for co in data:
            regions[co['region']].append({'value': co['cca3'], 'label': co['name']['common']})
        return [{'label': k, 'options': v} for k, v in regions.items()]


async def get_city(conn: Connection, city_id: int) -> City | None:
    row = await conn.fetchrow('SELECT * FROM cities WHERE id=$1', city_id)
    if row:
        return City(**row)


async def create_cities(conn: Connection):
    cities_exists = await conn.fetchval('SELECT EXISTS (SELECT 1 FROM cities)')
    if cities_exists:
        return
    columns = ', '.join(City.model_fields.keys())
    values = ', '.join(f'${i}' for i, _ in enumerate(City.model_fields, start=1))
    await conn.executemany(
        f'INSERT INTO cities ({columns}) VALUES ({values})', [tuple(v for _, v in c) for c in _load_cities()]
    )


def _load_cities() -> list[City]:
    cities_file = Path(__file__).parent / 'cities.json'
    cities = cities_adapter.validate_json(cities_file.read_bytes())
    cities.sort(key=lambda city: city.population, reverse=True)
    return cities
