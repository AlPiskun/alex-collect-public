#!/usr/bin/env python3
"""Headless checks for task layout and always-visible console replies."""
from pathlib import Path
import sys
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import gui  # noqa: E402


def check(name, condition, extra=""):
    """Assert one fact, naming what was actually there when it is not.

    ``extra`` is optional and only used on failure, which is where a bare
    name costs a trip back to the source to find out what the value really
    was. Every other suite's check() has the same third argument.
    """
    if not condition:
        raise AssertionError(name if not extra else "%s - got %s"
                             % (name, extra))
    print("PASS", name)


class Console:
    def __init__(self):
        self.last_insert = ""
        self.last_scroll = None

    def config(self, **_kwargs):
        pass

    def insert(self, _index, text, *_tags):
        self.last_insert = text

    def see(self, index):
        self.last_scroll = index


def main():
    console = Console()
    app = SimpleNamespace(console=console)
    gui.App.console_write(app, "tool output")
    gui.App.console_line(app, "> typed reply", "cmd")
    check("new output and typed replies always scroll into view",
          console.last_insert == "> typed reply\n" and
          console.last_scroll == "end" and
          not hasattr(gui.App, "_console_following_tail"))

    task_ids = {pid for _group, ids in gui.groups_for(True) for pid in ids}
    check("settings, plugins, and logs are removed from task buttons",
          not ({"cookie", "plugins", "logs"} & task_ids))
    core_ids = {pid for _group, ids in gui.groups_for(False) for pid in ids}
    check("core task menu omits plugin-only tasks",
          not ({"stage", "wire", "zerostock"} & core_ids))
    check("task sections are Sell to a customer, Sell a new batch, After a "
          "sale, Print an order, Photos, and Re-run",
          [name for name, _ids in gui.groups_for(True)] ==
          ["Sell to a customer", "Sell a new batch", "After a sale",
           "Print an order", "Photos", "Re-run a marketplace"],
          [name for name, _ids in gui.groups_for(True)])
    #  The sheet prints any order, not only the one just sold - so it is its
    #  own box after the after-a-sale jobs, and the last section of that tab.
    check("the order sheet sits after the after-a-sale group, in both menus",
          dict(gui.groups_for(True))["Print an order"] == ["ordersheet"] and
          dict(gui.groups_for(False))["Print an order"] == ["ordersheet"] and
          gui.TAB_HOME == {"ordersheet": "After a sale"} and
          gui.PANEL_BUILDERS["ordersheet"] is gui.build_ordersheet)
    #  It leads the first group rather than being the first group: since the
    #  customer quote arrived it shares "Sell to a customer" with it, and the
    #  claim worth making is that it is still the first thing offered.
    check("the order-from-a-list panel leads the tasks",
          gui.groups_for(True)[0][0] == "Sell to a customer" and
          gui.groups_for(True)[0][1][0] == "ordertext" and
          gui.groups_for(False)[0][1][0] == "ordertext" and
          gui.PANEL_BUILDERS["ordertext"] is gui.build_ordertext,
          str([(name, ids) for name, ids in gui.groups_for(True)][:1]))
    re_run_group = [ids for name, ids in gui.groups_for(True)
                    if name == "Re-run a marketplace"]
    check("the re-run panel is its own task section and tab",
          re_run_group == [["markets"]] and
          gui.TITLES["markets"] == "Re-run a marketplace step" and
          gui.PANEL_BUILDERS["markets"] is gui.build_markets)
    check("every marketplace can be re-run on its own",
          list(gui.MARKET_RERUNS) == ["woocommerce", "canadianshopper",
                                      "facebook", "ebay"] and
          set(gui.RERUN_NEEDS_CARDS) == {"woocommerce", "canadianshopper",
                                         "ebay"})
    check("CanadianShopper repair has a short label and plugin-aware tooltip",
          gui.MENU_LABELS["rerun"] == "Re-point photos" and
          "CanadianShopper plugin" in gui.BLURBS["rerun"])
    check("hover-tooltip helper is present", hasattr(gui, "ToolTip"))
    check("CanadianShopper draft publisher is a plugin-provided app tool",
          gui.CS_TOOL_ACTIONS.get("cs-publish-drafts.py") ==
          "marketplace.publish_drafts")
    check("built-in AI action names are clear",
          gui.PROMPT_TITLES == {"multi": "Add grades to titles",
                                "single": "No grades in titles"})
    check("built-in AI actions explain grade inclusion or omission",
          "multiple grades" in gui.PROMPT_TOOLTIPS["multi"] and
          "one grade" in gui.PROMPT_TOOLTIPS["single"])
    source = (HERE / "gui.py").read_text(encoding="utf-8")
    pipeline = source.split("def build_pipeline", 1)[1].split(
        "def build_combine", 1)[0]
    check("draft preview/apply controls are embedded in the pipeline panel",
          "_build_draft_publisher_controls(box, app)" in pipeline)
    check("draft publisher panel offers preview and confirmed apply",
          'text="Preview drafts"' in source and
          'text="Publish ready drafts"' in source and
          'args.append("--apply")' in source and
          'typing PUBLISH' in source)
    #  This used to pin a literal height=20 that the console had before it
    #  started sharing the window with the page. The size is computed from the
    #  screen now (console_lines_for), so the claim is the one that still
    #  matters: the console is sized by the screen, and it never shrinks to a
    #  couple of lines on the smallest screen the app supports.
    check("the console gives room to a tool's output on every screen",
          "console_lines_for(screen)" in source and
          gui.console_lines_for(600) >= 8,
          "%r lines on a 600-high screen" % gui.console_lines_for(600))
    task_ui = source.split("# ------------------------------------------------------------ task menu", 1)[1].split(
        "# --------------------------------------------------------------- tabs", 1)[0]
    check("task view has no headline and buttons do not stretch",
          'text="What do you want to do today?"' not in task_ui and
          'sticky="w"' in task_ui and 'sticky="ew"' not in task_ui)


if __name__ == "__main__":
    main()
