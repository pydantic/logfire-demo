# logfire-demo

Describe your project here.

## Runing the demo

1. Go to the [logfire dashboard](https://logfire.pydantic.dev/) and create a new project there.
2. Create a new write token for the project and copy it.
3. Set the `LOGFIRE_TOKEN` environment variable. `export LOGFIRE_TOKEN=<write token from step 2>`.
4. Create a new github token by `gh auth token`.
5. Set the `GITHUB_TOKEN` environment variable. `export GITHUB_TOKEN=<github token from step 4>`.
6. Run `docker-compose run -d`.

Now you can go to the [Logfire demo page](http://localhost:8000/) and surf different part of it.

You can find your project `Dashboard` link at the end of the page. Click on the dashboard link
to see the live logs from the demo project.
