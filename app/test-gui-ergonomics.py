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
    def __init__(self, view=(0.0, 1.0)):
        self.last_insert = ""
        self.last_scroll = None
        self.view = view

    def config(self, **_kwargs):
        pass

    def insert(self, _index, text, *_tags):
        self.last_insert = text

    def see(self, index):
        self.last_scroll = index

    def yview(self, *_args):
        """Where the visible window is: (first, last) fractions of the text."""
        return self.view


def main():
    console = Console()
    app = SimpleNamespace(console=console)
    gui.App.console_write(app, "tool output")
    gui.App.console_line(app, "> typed reply", "cmd")
    check("new output and typed replies scroll into view when the end is on "
          "screen",
          console.last_insert == "> typed reply\n" and
          console.last_scroll == "end")

    #  A read that prints for minutes must not yank the view back down every
    #  time it says something: once the person has scrolled up into the run,
    #  new lines land below the view and it stays where they put it.
    scrolled_up = Console(view=(0.0, 0.35))
    gui.App.console_write(SimpleNamespace(console=scrolled_up), "more output")
    gui.App.console_line(SimpleNamespace(console=scrolled_up), "another line",
                         "dim")
    check("output does not jump the console when the reader has scrolled up",
          scrolled_up.last_scroll is None and
          scrolled_up.last_insert == "another line\n")
    at_bottom = Console(view=(0.0, 0.9995))
    gui.App.console_line(SimpleNamespace(console=at_bottom), "line")
    check("a view within a rounding error of the end still follows it",
          at_bottom.last_scroll == "end")
    check("a console that cannot say where it is behaves as it always did",
          gui.at_end_of_console(None) and gui.at_end_of_console(()) and
          gui.at_end_of_console((0.0, 1.0)) and
          not gui.at_end_of_console((0.0, 0.5)))

    task_ids = {pid for _group, ids in gui.groups_for(True) for pid in ids}
    check("settings, plugins, and logs are removed from task buttons",
          not ({"cookie", "plugins", "logs"} & task_ids))
    #  Comparing and editing are one job, so the stock work left "After a
    #  sale" for a section of its own, with one place per marketplace and the
    #  shop's own two jobs inside its place.
    check("the stock work has its own section, one per marketplace",
          dict(gui.groups_for(True))["Edit stock"] ==
          ["stock", "editfb", "editeb"] and
          dict(gui.groups_for(False))["Edit stock"] ==
          ["square", "newphotos", "editfb", "editeb"],
          str(dict(gui.groups_for(False))["Edit stock"]))
    #  Every id a section offers must be a panel: a title, a blurb, a sentence
    #  of help, a menu label and a builder for each. A panel added to the menu
    #  without one of them is a button that opens nothing - which is what the
    #  window suite caught on the Edit stock section, and this catches here,
    #  where it can be run without a display.
    ids = set(gui.PANEL_ORDER)
    check("every panel in the order has a title, a blurb and a builder",
          set(gui.TITLES) == ids and set(gui.BLURBS) == ids and
          set(gui.PANEL_BUILDERS) == ids,
          str(sorted((set(gui.TITLES) ^ ids) | (set(gui.BLURBS) ^ ids) |
                     (set(gui.PANEL_BUILDERS) ^ ids))))
    check("and a menu label and its own help",
          set(gui.MENU_LABELS) == ids and
          not (ids - {"welcome"} - set(gui.DOCS)),
          str(sorted((set(gui.MENU_LABELS) ^ ids) |
                     (ids - {"welcome"} - set(gui.DOCS)))))
    check("every id a section offers is a real panel",
          all(pid in gui.PANEL_BUILDERS
              for _name, group in gui.groups_for(True) + gui.groups_for(False)
              for pid in group), "")
    check("and the shop's own section is named for the shop",
          gui.TITLES["stock"] == "Edit stock - CanadianShopper" and
          gui.TITLES["editfb"] == "Edit stock - Facebook" and
          gui.TITLES["editeb"] == "Edit stock - eBay" and
          gui.MENU_LABELS["stock"] == "CanadianShopper" and
          gui.MENU_LABELS["editfb"] == "Facebook" and
          gui.MENU_LABELS["editeb"] == "eBay", "")
    check("and it is its own panel, with its own help",
          gui.TITLES["csedit"] == "Find and edit a CanadianShopper listing" and
          gui.PANEL_BUILDERS["csedit"] is gui.build_csledit and
          "csedit" in gui.DOCS and gui.MENU_LABELS["csedit"] ==
          "Find a CS listing", "")
    core_ids = {pid for _group, ids in gui.groups_for(False) for pid in ids}
    check("core task menu omits plugin-only tasks",
          not ({"stage", "wire", "zerostock", "rerun"} & core_ids))
    check("task sections are Sell to a customer, Sell a new batch, After a "
          "sale, and Edit stock",
          [name for name, _ids in gui.groups_for(True)] ==
          ["Sell to a customer", "Sell a new batch", "After a sale",
           "Edit stock"],
          [name for name, _ids in gui.groups_for(True)])
    #  The shop's three photo tools moved into the shop's place, so they are
    #  stacked inside the CanadianShopper tab rather than having a tab of their
    #  own - and they have their own buttons on the panel in the task menu.
    check("the shop's photo tools are stacked in the shop's tab",
          [pid for pid in gui.TAB_EXTRA["Edit stock"]] ==
          ["csedit", "zerostock", "square", "rerun", "newphotos"],
          str(gui.TAB_EXTRA["Edit stock"]))
    check("and none of them is a task of its own",
          not ({"square", "rerun", "newphotos"} &
               {pid for _group, ids in gui.groups_for(True) for pid in ids}),
          "")
    check("while the core menu keeps the two that need no plugin",
          {"square", "newphotos"} <=
          {pid for _group, ids in gui.groups_for(False) for pid in ids},
          "")
    #  The three separate marketplace steps that used to have their own box
    #  are gone from the menu: the pipeline does that work itself, and the
    #  re-run panel is where a step that needs repeating is repeated.
    all_ids = {pid for _group, ids in gui.groups_for(True) for pid in ids}
    core_all = {pid for _group, ids in gui.groups_for(False)
                for pid in ids}
    check("staging, importing and wiring are no longer task buttons",
          not ({"stage", "importpanel", "wire"} & (all_ids | core_all)),
          str(sorted(all_ids)))
    check("their panels still exist, so old shortcuts and plugins still open "
          "them",
          all(pid in gui.PANEL_BUILDERS for pid in ("stage", "importpanel",
                                                    "wire")))
    check("the order sheet is an after-a-sale job now, in both menus",
          dict(gui.groups_for(True))["After a sale"][-1] == "ordersheet" and
          dict(gui.groups_for(False))["After a sale"][-1] == "ordersheet" and
          gui.PANEL_BUILDERS["ordersheet"] is gui.build_ordersheet,
          str(dict(gui.groups_for(True))["After a sale"]))
    #  It leads the first group rather than being the first group: since the
    #  customer quote arrived it shares "Sell to a customer" with it, and the
    #  claim worth making is that it is still the first thing offered.
    check("the order-from-a-list panel leads the tasks",
          gui.groups_for(True)[0][0] == "Sell to a customer" and
          gui.groups_for(True)[0][1][0] == "ordertext" and
          gui.groups_for(False)[0][1][0] == "ordertext" and
          gui.PANEL_BUILDERS["ordertext"] is gui.build_ordertext,
          str([(name, ids) for name, ids in gui.groups_for(True)][:1]))
    batch_group = [list(ids) for name, ids in gui.groups_for(True)
                   if name == "Sell a new batch"]
    check("the re-run panel sits with the batch it re-runs",
          batch_group == [["pipeline", "combine", "ebayfill", "markets"]] and
          gui.TITLES["markets"] == "Re-run a marketplace step" and
          gui.PANEL_BUILDERS["markets"] is gui.build_markets, str(batch_group))
    check("filling the eBay store is a batch job, with its own panel and help",
          "ebayfill" in batch_group[0] and
          gui.TITLES["ebayfill"] == "Fill your eBay store" and
          gui.PANEL_BUILDERS["ebayfill"] is gui.build_ebayfill and
          "ebayfill" in gui.DOCS and gui.MENU_LABELS["ebayfill"] ==
          "Fill the eBay store", str(batch_group))
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
