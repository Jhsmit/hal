"""
a collection of solara components
"""

import altair as alt
import polars as pl
import solara


@solara.component
def ScatterPlot(df: pl.DataFrame):
    """A scatter plot of two user-selectable columns"""
    columns = df.columns
    x_col = solara.use_reactive(columns[0])
    y_col = solara.use_reactive(columns[1])

    chart = (
        alt.Chart(df)
        .mark_point()
        .encode(
            x=x_col.value,
            y=y_col.value,
            tooltip=[x_col.value, y_col.value],
        )
        .interactive()
    )

    with solara.Row():
        solara.Select(label="X", values=columns, value=x_col)
        solara.Select(label="Y", values=columns, value=y_col)

    alt.JupyterChart.element(chart=chart)
