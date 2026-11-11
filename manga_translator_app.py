"""Launcher kept for compatibility: `python manga_translator_app.py` opens the GUI.

After `pip install -e .` you can also run `mangatraductor-gui`.
"""

from mangatraductor.gui import main

if __name__ == "__main__":
    main()
