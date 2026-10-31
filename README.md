# kigit

**kigit** utilizes the use of git logs in order to allow user to perform diffs between their pcb and schematic files. It provides a proper visual feedback which helps in identifying changes made per commit basis. Hence where its name came from, combination of Ki from KiCAD and git itself (kigit!). 

What it can do:

- Compare your PCB between any two commits, visually
- Show what changed on your symbols and their fields
- Show your buses and where they're routed
- Work without git too: just point it at two folders (see [Without Git](examples/without-git.md))

Have a look at the demo below to get a feel for it.

## Demonstration

<video autoplay loop muted controls width="100%">
  <source src="https://github.com/user-attachments/assets/a7a2acdf-94fa-4d13-9619-224367c1c7df" type="video/mp4">
</video>

![Example](https://github.com/user-attachments/assets/a7a2acdf-94fa-4d13-9619-224367c1c7df)

---

## What kigit is not

kigit is an application that was built out of frustration of not having a kind of proper "git diff" for kicad for myself. Having came from a software background and being used to utilizing git versioning for all of my projects, not being able to do the same in a manner that I can compare my pcb and schematic visually between different commits without having to diff the .kicad_pcb and .kicad_sch files really frustates me. I am aware of the fact that there are other resources out there as shown below:

- [KiRI](https://github.com/leoheck/kiri)
- [KiCAD-Prism](https://krishna-swaroop.github.io/KiCAD-Prism/get-started/what-is-prism/)
- [KiHub](https://kihub.dev/)

They all have their pros and cons. KiRI is what got me excited about diffing schematics in the first place, and honestly, huge respect to the folks behind it. It's a great community effort, built well before AI was a thing.

The other two I didn't even know existed when I started. Funnily enough, not even Claude mentioned them when I first went looking for alternatives.

KiCAD-Prism and KiHub are in the same space and cover a lot of what kigit does. KiCAD-Prism is a whole package: free, open source, and the demos look amazing. But it needs a fair bit of Docker setup, which can be a turn-off if you're a hobbyist who just wants to design boards. KiHub needs a login, doesn't run offline, and is really aimed at teams collaborating (PR reviews and that kind of thing).

Me? I'm a hobbyist who only recently got into PCB design and out of this frustration, I figured: why not just make my own PCB diff that does just enough for what I need? Nothing fancy. It runs locally, it's a simple download, and it works on Linux and Windows. (Sorry macOS folks, I'm broke and not about to buy a Mac just for this.)

So, what kigit is **not** is a collaboration tool. It's for people who wants a simple app they can download, or open in a browser, to check what changed in their PCB designs. That's it.

!!! warning "Disclaimer"
    When I say "I built it", it was mostly my best mate, Claude.

## Quick start

```sh
cd path/to/my-board        # a KiCad project in a git repository
kigit HEAD~1               # the last commit vs your working tree
kigit gui                  # or pick commits in the GUI
```

See [Installation](installation.md) to get kigit, and [Overview](how-to-use/overview.md) for how it works.
