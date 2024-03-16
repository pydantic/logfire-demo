import pydantic
from fastapi import APIRouter
from fastapi.exceptions import HTTPException
from fastui import AnyComponent, FastUI
from fastui import components as c
from fastui.components.display import DisplayLookup
from fastui.events import BackEvent, GoToEvent
from fastui.forms import SelectSearchResponse
from pydantic import Field


from .shared import demo_page
from ..common.db import Database
from ..common import cities, AsyncClientDep

router = APIRouter()


class FilterForm(pydantic.BaseModel):
    country: str = Field(
        None, json_schema_extra={'search_url': '/api/table/search', 'placeholder': 'Filter by Country...'}
    )


@router.get('', response_model=FastUI, response_model_exclude_none=True)
async def cities_view(db: Database, page: int = 1, country: str | None = None) -> list[AnyComponent]:
    async with db.acquire() as conn:
        if country:
            table_cities, count = await cities.filter_cities(conn, country, (page - 1) * cities.PAGE_LIMIT)
            country_name = table_cities[0].country if cities else country
            filter_form_initial = {'country': {'value': country, 'label': country_name}}
        else:
            table_cities, count = await cities.list_cities(conn, (page - 1) * cities.PAGE_LIMIT)
            filter_form_initial = {}
    return demo_page(
        c.ModelForm(
            model=FilterForm,
            submit_url='.',
            initial=filter_form_initial,
            method='GOTO',
            submit_on_change=True,
            display_mode='inline',
        ),
        c.Table(
            data=table_cities,
            data_model=cities.City,
            columns=[
                DisplayLookup(field='city', on_click=GoToEvent(url='./{id}'), table_width_percent=33),
                DisplayLookup(field='country', table_width_percent=33),
                DisplayLookup(field='population', table_width_percent=33),
            ],
        ),
        c.Pagination(page=page, page_size=cities.PAGE_LIMIT, total=count),
        title='Cities',
    )


@router.get('/search', response_model=SelectSearchResponse)
async def search_view(http_client: AsyncClientDep, q: str) -> SelectSearchResponse:
    options = await cities.search_name(http_client, q)
    return SelectSearchResponse(options=options)


@router.get('/{city_id}', response_model=FastUI, response_model_exclude_none=True)
async def city_view(db: Database, city_id: int) -> list[AnyComponent]:
    async with db.acquire() as conn:
        city = await cities.get_city(conn, city_id)
    if not city:
        raise HTTPException(status_code=404, detail='City not found')
    return demo_page(
        c.Link(components=[c.Text(text='Back')], on_click=BackEvent()),
        c.Details(data=city),
        title=city.city,
    )
