from cfbtui.app import CfbApp, Swatch
from cfbtui.ui.widgets.status_bar import StatusBar


async def test_app_boots_and_paints_swatches():
    app = CfbApp()
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        swatches = app.query(Swatch)
        assert len(swatches) == 6
        backgrounds = {str(s.styles.background) for s in swatches}
        assert len(backgrounds) == 6, "every swatch should carry a distinct team color"
        status = app.query_one(StatusBar)
        assert "cfbtui v" in str(status.content)
