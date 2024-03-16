from __future__ import annotations as _annotations

from fastui import AnyComponent
from fastui import components as c
from fastui.events import GoToEvent


def demo_page(*components: AnyComponent, title: str | None = None) -> list[AnyComponent]:
    return [
        c.PageTitle(text=f'Logfire Demo — {title}' if title else 'Logfire Demo'),
        c.Navbar(
            title='Logfire Demo',
            title_event=GoToEvent(url='/'),
            end_links=[
                c.Link(
                    components=[c.Text(text='Login')],
                    on_click=GoToEvent(url='/auth/login/password'),
                    active='startswith:/auth',
                ),
            ],
        ),
        c.Page(
            components=[
                *((c.Heading(text=title),) if title else ()),
                *components,
            ],
        ),
        c.Footer(
            extra_text='Logfire Demo',
            links=[
                c.Link(components=[c.Text(text='Docs')], on_click=GoToEvent(url='https://docs.logfire.dev')),
                c.Link(components=[c.Text(text='Dashboard')], on_click=GoToEvent(url='https://dash.logfire.dev')),
                c.Link(components=[c.Text(text='PyPI')], on_click=GoToEvent(url='https://pypi.org/project/logfire/')),
            ],
        ),
    ]
