#!/usr/bin/python3
"""

Panel - Displays a window with various widgets at the top of the screen.

This panel is based on the original C implementation in ToaruOS, but is focused
on providing a more easily extended widget system. Each element of the panel is
a widget object which can independently draw and receive mouse events.

"""
import configparser
import html
import math
import os
import signal
import sys
import time

import cairo

import yutani
import text_region
import toaru_fonts

from menu_bar import MenuEntryAction, MenuEntrySubmenu, MenuEntryDivider, MenuWindow
from icon_cache import get_icon

PANEL_HEIGHT=28

class BaseWidget(object):
    """Base class for a panel widget."""

    width = 0

    def draw(self, window, offset, remaining, ctx):
        pass

    def focus_enter(self):
        pass

    def focus_leave(self):
        pass

    def mouse_action(self, msg):
        return False

class ClockWidget(BaseWidget):
    """Displays a simple clock"""

    text_y_offset = 4
    width = 80
    color = 0xFFE6E6E6

    def __init__(self):
        self.font = toaru_fonts.Font(toaru_fonts.FONT_SANS_SERIF_BOLD, 16, self.color)
        self.tr   = text_region.TextRegion(0,0,self.width,PANEL_HEIGHT-self.text_y_offset,font=self.font)

    def draw(self, window, offset, remaining, ctx):
        self.tr.move(offset,self.text_y_offset)
        self.tr.set_text(time.strftime('%H:%M:%S',time.localtime(current_time)))
        self.tr.draw(window)

    def focus_enter(self):
        self.font.font_color = 0xFF8EDBFF

    def focus_leave(self):
        self.font.font_color = self.color

class DateWidget(BaseWidget):
    """Displays the weekday and date on separate lines."""

    text_y_offset = 4
    color = 0xFFE6E6E6
    width = 70

    def __init__(self):
        self.font = toaru_fonts.Font(toaru_fonts.FONT_SANS_SERIF, 9, self.color)
        self.tr   = text_region.TextRegion(0,0,self.width,PANEL_HEIGHT-self.text_y_offset,font=self.font)
        self.tr.set_alignment(2)

    def draw(self, window, offset, remaining, ctx):
        self.tr.move(offset,self.text_y_offset)
        lt = time.localtime(current_time)
        weekday = time.strftime('%A',lt)
        date = time.strftime('%h %e',lt)
        self.tr.set_richtext(f"{weekday}\n<b>{date}</b>")
        self.tr.draw(window)

class LogOutWidget(BaseWidget):
    """Simple button widget that ends the user session when clicked."""
    # TODO: Present a log out / restart menu instead.

    width = 28

    path = '/usr/share/icons/panel-shutdown.png'

    def __init__(self):
        self.icon = cairo.ImageSurface.create_from_png(self.path)
        self.icon_hilight = cairo.ImageSurface.create_from_png(self.path)
        tmp = cairo.Context(self.icon_hilight)
        tmp.set_operator(cairo.OPERATOR_ATOP)
        tmp.rectangle(0,0,24,24)
        tmp.set_source_rgb(0x8E/0xFF,0xD8/0xFF,1)
        tmp.paint()
        self.hilighted = False

    def draw(self, window, offset, remaining, ctx):
        if self.hilighted:
            ctx.set_source_surface(self.icon_hilight,offset+2,1)
        else:
            ctx.set_source_surface(self.icon,offset+2,1)
        ctx.paint()

    def focus_enter(self):
        self.hilighted = True

    def focus_leave(self):
        self.hilighted = False

    def mouse_action(self, msg):
        if msg.command == yutani.MouseEvent.CLICK:
            yctx.session_end()
        return False

class VolumeWidget(BaseWidget):
    """Volume control widget."""

    width = 28
    color = 0xFFE6E6E6
    icon_names = ['volume-mute','volume-low','volume-medium','volume-full']

    def __init__(self):
        self.icons = {}
        for name in self.icon_names:
            self.icons[name] = get_icon(name)
        self.mixer_fd = open('/dev/mixer')
        self.volume = self.get_volume()
        self.muted = False
        self.previous_volume = 0

    def draw(self, window, offset, remaining, ctx):
        if self.volume < 10:
            source = 'volume-mute'
        elif self.volume < 0x547ae147:
            source = 'volume-low'
        elif self.volume < 0xa8f5c28e:
            source = 'volume-medium'
        else:
            source = 'volume-full'
        ctx.set_source_surface(self.icons[source],offset,0)
        ctx.paint()

    def get_volume(self):
        """Get the current mixer master volume."""
        import fcntl
        import struct
        knob = bytearray(struct.pack("III", 0, 0, 0)) # VOLUME_DEVICE_ID, VOLUME_KNOB_ID, <Unused>
        fcntl.ioctl(self.mixer_fd, 2, knob, True)
        _,_,value = struct.unpack("III", knob)
        return value

    def set_volume(self):
        """Set the mixer master volume to the widget's volume level."""
        import fcntl
        import struct
        knob = struct.pack("III", 0, 0, self.volume) # VOLUME_DEVICE_ID, VOLUME_KNOB_ID, volume_level
        fcntl.ioctl(self.mixer_fd, 3, knob)

    def volume_up(self):
        if self.volume > 0xE0000000:
            self.volume = 0xF0000000
        else:
            self.volume += 0x10000000
        self.set_volume()

    def volume_down(self):
        if self.volume < 0x20000000:
            self.volume = 0x0
        else:
            self.volume -= 0x10000000
        self.set_volume()

    def mouse_action(self, msg):
        if msg.command == yutani.MouseEvent.CLICK:
            if self.muted:
                self.muted = False
                self.volume = self.previous_volume
                self.set_volume()
            else:
                self.muted = True
                self.previous_volume = self.volume
                self.volume = 0
                self.set_volume()
            return True
        else:
            if msg.buttons & yutani.MouseButton.SCROLL_UP:
                self.volume_up()
                return True
            elif msg.buttons & yutani.MouseButton.SCROLL_DOWN:
                self.volume_down()
                return True

class WindowListWidget(BaseWidget):
    """Displays a list of windows with icons and titles."""

    width = -1
    text_y_offset = 5
    color = 0xFFE6E6E6
    hilight = 0xFF8ED8FF
    icon_width = 24

    def __init__(self):
        self.font = toaru_fonts.Font(toaru_fonts.FONT_SANS_SERIF, 13, self.color)
        self.font_hilight = toaru_fonts.Font(toaru_fonts.FONT_SANS_SERIF, 13, self.hilight)
        self.gradient = cairo.LinearGradient(0,0,0,PANEL_HEIGHT)
        self.gradient.add_color_stop_rgba(0.0,72/255,167/255,255/255,0.7)
        self.gradient.add_color_stop_rgba(1.0,72/255,167/255,255/255,0.0)
        self.hovered = None
        self.unit_width = None
        self.offset = 0

    def draw(self, window, offset, remaining, ctx):
        global windows
        if not len(windows):
            return
        self.window = window
        self.offset = offset
        available_width = remaining - offset
        self.unit_width = min(int(available_width / len(windows)),150)
        if self.unit_width < 50:
            self.unit_width = 28
        for w in windows:
            if w.flags & 1:
                ctx.set_source(self.gradient)
                ctx.rectangle(offset,0,self.unit_width,PANEL_HEIGHT)
                ctx.fill()
            icon = get_icon(w.icon)

            ctx.save()
            ctx.translate(offset+2,0)
            if icon.get_width() != self.icon_width:
                ctx.scale(self.icon_width/icon.get_width(),self.icon_width/icon.get_width())
            ctx.set_source_surface(icon,0,0)
            ctx.paint()
            ctx.restore()

            if self.unit_width > 28:
                font = self.font
                if self.hovered == w.wid:
                    font = self.font_hilight
                tr = text_region.TextRegion(offset+28,self.text_y_offset,self.unit_width - 30,PANEL_HEIGHT-self.text_y_offset,font=font)
                tr.set_one_line()
                tr.set_ellipsis()
                tr.set_text(w.name)
                tr.draw(window)
            offset += self.unit_width

    def focus_leave(self):
        self.hovered = None

    def mouse_action(self, msg):
        if not len(windows):
            return
        msg.new_x -= self.offset
        hovered_index = int(msg.new_x / self.unit_width)
        previously_hovered = self.hovered
        if hovered_index < len(windows):
            self.hovered = windows[hovered_index].wid
            if msg.command == yutani.MouseEvent.CLICK:
                yctx.focus_window(self.hovered)
            elif msg.buttons & yutani.MouseButton.BUTTON_RIGHT:
                if not self.window.menus:
                    def move_window(window):
                        yutani.yutani_lib.yutani_window_drag_start_wid(yutani.yutani_ctx._ptr,window)
                    #def close_window(window):
                    #    print("Should close window",window)
                    menu_entries = [
                        MenuEntryAction("Move",None,move_window,self.hovered),
                        #MenuEntryAction("Close",None,close_window,self.hovered)
                    ]
                    menu = MenuWindow(menu_entries,(msg.new_x+self.offset,PANEL_HEIGHT),root=self.window)
        else:
            self.hovered = None
        return self.hovered != previously_hovered


class ApplicationsMenuWidget(BaseWidget):
    """Provides a menu of applications to launch."""

    text_y_offset = 4
    text_x_offset = 10
    color = 0xFFE6E6E6
    hilight = 0xFF8ED8FF

    def __init__(self):
        self.width = 140
        self.font = toaru_fonts.Font(toaru_fonts.FONT_SANS_SERIF_BOLD, 14, self.color)
        self.tr   = text_region.TextRegion(0,0,self.width-self.text_x_offset*2,PANEL_HEIGHT-self.text_y_offset,font=self.font)
        self.tr.set_text("Applications")
        self.menu_entries = [
            MenuEntrySubmenu("Accesories",[
                MenuEntryAction("Calculator","calculator",launch_app,"calculator.py"),
                MenuEntryAction("Clock Widget","clock",launch_app,"clock-win"),
                MenuEntryAction("File Browser","folder",launch_app,"file_browser.py"),
                MenuEntryAction("Terminal","utilities-terminal",launch_app,"terminal"),
                MenuEntryAction("Vim","vim",launch_app,"terminal vim-install-or-run.py"),
            ]),
            MenuEntrySubmenu("Demos",[
                MenuEntrySubmenu("Cairo",[
                    MenuEntryAction("Cairo Demo","cairo-demo",launch_app,"cairo-demo"),
                    MenuEntryAction("Cairo Snow","snow",launch_app,"make-it-snow"),
                    MenuEntryAction("Pixman Demo","pixman-demo",launch_app,"pixman-demo"),
                ]),
                MenuEntrySubmenu("Mesa (swrast)",[
                    MenuEntryAction("Gears","gears",launch_app,"gears"),
                    MenuEntryAction("Teapot","teapot",launch_app,"teapot"),
                ]),
                MenuEntryAction("Draw Lines","drawlines",launch_app,"drawlines"),
                MenuEntryAction("Julia Fractals","julia",launch_app,"julia"),
                MenuEntryAction("Plasma","plasma",launch_app,"plasma"),
            ]),
            MenuEntrySubmenu("Games",[
                MenuEntryAction("RPG Demo","applications-simulation",launch_app,"game"),
            ]),
            MenuEntrySubmenu("Graphics",[
                MenuEntryAction("Draw!","applications-painting",launch_app,"draw"),
            ]),
            MenuEntrySubmenu("Settings",[
                MenuEntryAction("Select Wallpaper","select-wallpaper",launch_app,"select-wallpaper"),
            ]),
            MenuEntryDivider(),
            MenuEntryAction("Help","help",launch_app,"help-browser.py"),
            MenuEntryAction("About ToaruOS","star",launch_app,"about-applet.py"),
            MenuEntryAction("Log Out","exit",logout_callback,""),
        ]

    def draw(self, window, offset, remaining, ctx):
        self.window = window
        self.tr.move(offset+self.text_x_offset,self.text_y_offset)
        self.tr.draw(window)

    def focus_enter(self):
        self.font.font_color = self.hilight

    def focus_leave(self):
        self.font.font_color = self.color

    def activate(self):
        menu = MenuWindow(self.menu_entries,(0,PANEL_HEIGHT),root=self.window)

    def mouse_action(self,msg):
        if msg.command == yutani.MouseEvent.CLICK:
            self.activate()

class PanelWindow(yutani.Window):
    """The panel itself."""

    def __init__(self, widgets):
        self.widgets = widgets
        flags = yutani.WindowFlag.FLAG_NO_STEAL_FOCUS | yutani.WindowFlag.FLAG_DISALLOW_DRAG | yutani.WindowFlag.FLAG_DISALLOW_RESIZE
        super(PanelWindow, self).__init__(yutani.yutani_ctx._ptr.contents.display_width,PANEL_HEIGHT,doublebuffer=True,flags=flags)
        self.move(0,0)
        self.set_stack(yutani.WindowStackOrder.ZORDER_TOP)
        self.focused_widget = None

        self.menus = {}
        self.hovered_menu = None

        # Panel background
        self.background = cairo.ImageSurface.create_from_png('/usr/share/panel.png')
        self.background_pattern = cairo.SurfacePattern(self.background)
        self.background_pattern.set_extend(cairo.EXTEND_REPEAT)

        self.visible = True

    def toggle_visibility(self):
        if not self.visible:
            for i in range(PANEL_HEIGHT-1,-1,-1):
                self.move(0,-i)
                yutani.usleep(10000)
            self.visible = True
        else:
            for i in range(1,PANEL_HEIGHT,1):
                self.move(0,-i)
                yutani.usleep(10000)
            self.visible = False

    def draw(self):
        """Draw the window."""
        surface = self.get_cairo_surface()
        ctx = cairo.Context(surface)

        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.set_source(self.background_pattern)
        ctx.paint()
        ctx.set_operator(cairo.OPERATOR_OVER)

        offset = 0
        index = 0
        for widget in self.widgets:
            index += 1
            remaining = 0 if widget.width != -1 else self.width - sum([widget.width for widget in self.widgets[index:]])
            widget.draw(self, offset, remaining, ctx)
            offset = offset + widget.width if widget.width != -1 else remaining

        self.flip()

    def finish_resize(self, msg):
        self.resize_accept(msg.width, msg.height)
        self.reinit()
        self.draw()
        self.resize_done()
        self.flip()


    def mouse_action(self, msg):
        redraw = False
        if (msg.command == 5 or msg.new_y >= self.height) and self.focused_widget:
            self.focused_widget.focus_leave()
            self.focused_widget = None
            redraw = True
        elif msg.new_y < self.height:
            widget_under_mouse = None
            offset = 0
            index = 0
            for widget in self.widgets:
                index += 1
                remaining = 0 if widget.width != -1 else self.width - sum([widget.width for widget in self.widgets[index:]])
                if msg.new_x >= offset and msg.new_x < (offset + widget.width if widget.width != -1 else remaining):
                    widget_under_mouse = widget
                    break
                offset = offset + widget.width if widget.width != -1 else remaining
            if widget_under_mouse != self.focused_widget:
                if self.focused_widget:
                    self.focused_widget.focus_leave()
                    redraw = True
                self.focused_widget = widget_under_mouse
                if self.focused_widget:
                    self.focused_widget.focus_enter()
                    redraw = True
            elif widget_under_mouse:
                if widget_under_mouse.mouse_action(msg):
                    self.draw()
        if redraw:
            self.draw()


class WallpaperIcon(object):

    icon_width = 48
    width = 100
    height = 80

    def __init__(self, icon, name, action, data):
        self.name = name
        self.action = action
        self.data = data

        self.x = 0
        self.y = 0

        self.hilighted = False
        self.icon = get_icon(icon,self.icon_width)
        self.icon_hilight = cairo.ImageSurface(self.icon.get_format(),self.icon.get_width(),self.icon.get_height())
        tmp = cairo.Context(self.icon_hilight)
        tmp.set_operator(cairo.OPERATOR_SOURCE)
        tmp.set_source_surface(self.icon,0,0)
        tmp.paint()
        tmp.set_operator(cairo.OPERATOR_ATOP)
        tmp.rectangle(0,0,self.icon_hilight.get_width(),self.icon_hilight.get_height())
        tmp.set_source_rgba(0x8E/0xFF,0xD8/0xFF,1,0.3)
        tmp.paint()

        self.font = toaru_fonts.Font(toaru_fonts.FONT_SANS_SERIF, 13, 0xFFFFFFFF)
        self.font.set_shadow((0xFF000000, 2, 1, 1, 3.0))
        self.tr = text_region.TextRegion(0,0,self.width,15,font=self.font)
        self.tr.set_alignment(2)
        self.tr.set_text(self.name)
        self.tr.set_one_line()

    def draw(self, window, offset, ctx, animating=False):
        x, y = offset

        self.x = x
        self.y = y

        self.tr.move(x,y+self.icon_width+5)
        self.tr.draw(window)

        left_pad = int((self.width - self.icon_width)/2)

        icon = self.icon_hilight if self.hilighted else self.icon

        ctx.save()
        ctx.translate(x+left_pad,y)
        if icon.get_width() != self.icon_width:
            ctx.scale(self.icon_width/icon.get_width(),self.icon_width/icon.get_width())
        ctx.set_source_surface(icon,0,0)
        ctx.paint()
        ctx.restore()

        if animating and animating < 0.5:
            ctx.save()
            ctx.translate(x+left_pad,y)
            if icon.get_width() != self.icon_width:
                ctx.scale(self.icon_width/icon.get_width(),self.icon_width/icon.get_width())
            scale = 1.0 + animating/0.8
            n = (self.icon_width - self.icon_width * scale) / 2
            ctx.translate(n,0)
            ctx.scale(scale,scale)
            ctx.set_source_surface(icon,0,0)
            ctx.paint_with_alpha(1.0 - animating/0.5)
            ctx.restore()

    def focus_enter(self):
        self.hilighted = True

    def focus_leave(self):
        self.hilighted = False

    def mouse_action(self, msg):
        if msg.command == yutani.MouseEvent.CLICK:
            self.action(self)

class WallpaperWindow(yutani.Window):
    """Manages the desktop wallpaper window."""

    fallback = '/usr/share/wallpapers/default'

    def __init__(self):
        w = yutani.yutani_ctx._ptr.contents.display_width
        h = yutani.yutani_ctx._ptr.contents.display_height
        flags = yutani.WindowFlag.FLAG_NO_STEAL_FOCUS | yutani.WindowFlag.FLAG_DISALLOW_DRAG | yutani.WindowFlag.FLAG_DISALLOW_RESIZE
        super(WallpaperWindow, self).__init__(w,h,doublebuffer=True,flags=flags)
        self.move(0,0)
        self.set_stack(yutani.WindowStackOrder.ZORDER_BOTTOM)

        # TODO get the user's selected wallpaper
        self.background = self.load_wallpaper()
        self.icons = self.load_icons()
        self.focused_icon = None
        self.animations = {}
        self.x = 0 # For clipping
        self.y = 0

    def animate_new(self):
        self.new_background = self.load_wallpaper()
        self.animations[self] = time.time()

    def add_animation(self, icon):
        self.animations[icon] = time.time()

    def animate(self):
        tick = time.time()
        self.draw(self.animations.keys())
        ditch = []
        for icon in self.animations:
            if icon == self:
                continue
            if tick - self.animations[icon] > 0.5:
                ditch.append(icon)
        for icon in ditch:
            del self.animations[icon]


    def load_icons(self):
        home = os.environ['HOME']
        path = f'{home}/.desktop'
        if not os.path.exists(path):
            path = '/etc/default.desktop'
        icons = []
        with open(path) as f:
            for line in f:
                icons.append(line.strip().split(','))

        wallpaper = self
        def launch_application(self):
            wallpaper.add_animation(self)
            os.spawnvp(os.P_NOWAIT,'/bin/sh',['/bin/sh','-c',self.data])

        out = []
        for icon in icons:
            out.append(WallpaperIcon(icon[0],icon[2],launch_application,icon[1]))

        return out

    def load_wallpaper(self, path=None):
        if not path:
            home = os.environ['HOME']
            conf = f'{home}/.desktop.conf'
            if not os.path.exists(conf):
                path = self.fallback
            else:
                with open(conf,'r') as f:
                    conf_str = '[desktop]\n' + f.read()
                c = configparser.ConfigParser()
                c.read_string(conf_str)
                path = c['desktop'].get('wallpaper',self.fallback)
        return cairo.ImageSurface.create_from_png(path)

    def finish_resize(self, msg):
        self.resize_accept(msg.width, msg.height)
        self.reinit()
        self.draw()
        self.resize_done()
        self.flip()

    def draw(self, clips=None):
        """Draw the window."""
        surface = self.get_cairo_surface()
        ctx = cairo.Context(surface)

        ctx.save()

        if clips:
            for clip in clips:
                ctx.rectangle(clip.x,clip.y,clip.width,clip.height)
            if self.animations:
                for clip in self.animations:
                    ctx.rectangle(clip.x,clip.y,clip.width,clip.height)
            ctx.clip()
        ctx.set_operator(cairo.OPERATOR_SOURCE)

        x = self.width / self.background.get_width()
        y = self.height / self.background.get_height()

        nh = int(x * self.background.get_height())
        nw = int(y * self.background.get_width())

        if (nw > self.width):
            ctx.translate((self.width - nw) / 2, 0)
            ctx.scale(y,y)
        else:
            ctx.translate(0,(self.height - nh) / 2)
            ctx.scale(x,x)

        ctx.set_source_surface(self.background,0,0)
        ctx.paint()
        ctx.restore()


        ctx.set_operator(cairo.OPERATOR_OVER)
        clear_animation = False

        if self in self.animations:
            ctx.save()
            x = self.width / self.new_background.get_width()
            y = self.height / self.new_background.get_height()

            nh = int(x * self.new_background.get_height())
            nw = int(y * self.new_background.get_width())

            if (nw > self.width):
                ctx.translate((self.width - nw) / 2, 0)
                ctx.scale(y,y)
            else:
                ctx.translate(0,(self.height - nh) / 2)
                ctx.scale(x,x)

            ctx.set_source_surface(self.new_background,0,0)
            diff = time.time()-self.animations[self]
            if diff >= 1.0:
                self.background = self.new_background
                clear_animation = True
                ctx.paint()
            else:
                ctx.paint_with_alpha(diff/1.0)

            ctx.restore()

        offset_x = 20
        offset_y = 50
        last_width = 0
        for icon in self.icons:
            if offset_y > self.height - icon.height:
                offset_y = 50
                offset_x += last_width
                last_width = 0
            if icon.width > last_width:
                last_width = icon.width
            if not clips or icon in clips or icon in self.animations or self in self.animations:
                icon.draw(self,(offset_x,offset_y),ctx,time.time()-self.animations[icon] if icon in self.animations else False)
            offset_y += icon.height

        if clear_animation:
            del self.animations[self]

        self.flip()

    def mouse_action(self, msg):
        redraw = False
        clips = []
        if (msg.command == 5 or msg.new_y >= self.height) and self.focused_icon:
            self.focused_icon.focus_leave()
            clips.append(self.focused_icon)
            self.focused_icon = None
            redraw = True
        else:
            icon_under_mouse = None
            offset_x = 20
            offset_y = 50
            last_width = 0
            for icon in self.icons:
                if offset_y > self.height - icon.height:
                    offset_y = 50
                    offset_x += last_width
                    last_width = 0
                if icon.width > last_width:
                    last_width = icon.width
                if msg.new_x >= offset_x and msg.new_x < offset_x + icon.width and msg.new_y >= offset_y and msg.new_y < offset_y + icon.height:
                    icon_under_mouse = icon
                    break
                offset_y += icon.height
            if icon_under_mouse != self.focused_icon:
                if self.focused_icon:
                    self.focused_icon.focus_leave()
                    redraw = True
                    clips.append(self.focused_icon)
                self.focused_icon = icon_under_mouse
                if self.focused_icon:
                    self.focused_icon.focus_enter()
                    redraw = True
                    clips.append(self.focused_icon)
            elif icon_under_mouse:
                if icon_under_mouse.mouse_action(msg):
                    self.draw()
                    clips.append(icon_under_mouse)
        if redraw:
            self.draw(clips)

class AlttabWindow(yutani.Window):
    """Displays the currently selected window for Alt-Tab switching."""

    icon_width = 48
    color = 0xFFE6E6E6

    def __init__(self):
        flags = yutani.WindowFlag.FLAG_NO_STEAL_FOCUS | yutani.WindowFlag.FLAG_DISALLOW_DRAG | yutani.WindowFlag.FLAG_DISALLOW_RESIZE
        super(AlttabWindow,self).__init__(300,115,doublebuffer=True,flags=flags)
        w = yutani.yutani_ctx._ptr.contents.display_width
        h = yutani.yutani_ctx._ptr.contents.display_height
        self.move(int((w-self.width)/2),int((h-self.height)/2))
        self.font = toaru_fonts.Font(toaru_fonts.FONT_SANS_SERIF_BOLD, 14, self.color)

    def draw(self):
        surface = self.get_cairo_surface()
        ctx = cairo.Context(surface)

        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.rectangle(0,0,self.width,self.height)
        ctx.set_source_rgba(0,0,0,0)
        ctx.fill()

        ctx.set_operator(cairo.OPERATOR_OVER)
        rounded_rectangle(ctx,0,0,self.width,self.height,10)
        ctx.set_source_rgba(0,0,0,0.7)
        ctx.fill()

        if new_focused >= 0 and new_focused < len(windows_zorder):
            w = windows_zorder[new_focused]

            icon = get_icon(w.icon,self.icon_width)

            ctx.save()
            ctx.translate(int((self.width-self.icon_width)/2),20)
            if icon.get_width() != self.icon_width:
                ctx.scale(self.icon_width/icon.get_width(),self.icon_width/icon.get_width())
            ctx.set_source_surface(icon,0,0)
            ctx.paint()
            ctx.restore()

            font = self.font
            tr = text_region.TextRegion(0,70,self.width,30,font=font)
            tr.set_one_line()
            tr.set_ellipsis()
            tr.set_alignment(2)
            tr.set_text(w.name)
            tr.draw(self)


        self.flip()

class ApplicationRunnerWindow(yutani.Window):
    """Displays the currently selected window for Alt-Tab switching."""

    icon_width = 48
    color = 0xFFE6E6E6

    def __init__(self):
        super(ApplicationRunnerWindow,self).__init__(400,115,doublebuffer=True)
        w = yutani.yutani_ctx._ptr.contents.display_width
        h = yutani.yutani_ctx._ptr.contents.display_height
        self.move(int((w-self.width)/2),int((h-self.height)/2))
        self.font = toaru_fonts.Font(toaru_fonts.FONT_SANS_SERIF_BOLD, 16, self.color)
        self.data = ""
        self.complete = ""
        self.completed = False
        self.bins = []
        for d in os.environ.get("PATH").split(":"):
            if os.path.exists(d):
                self.bins.extend(os.listdir(d))

    def close(self):
        global app_runner
        app_runner = None
        super(ApplicationRunnerWindow,self).close()

    def try_complete(self):
        if not self.data:
            self.complete = ""
            self.completed = False
            return
        for b in sorted(self.bins):
            if b.startswith(self.data):
                self.complete = b[len(self.data):]
                self.completed = True
                return
        self.completed = False
        self.complete = ""

    def key_action(self, msg):
        if not msg.event.action == yutani.KeyAction.ACTION_DOWN:
            return
        if msg.event.keycode == yutani.Keycode.ESCAPE:
            self.close()
            return
        if msg.event.keycode == yutani.Keycode.DEL:
            self.complete = ""
            self.completed = False
            self.draw()
            return
        if msg.event.key == b'\x00':
            return
        if msg.event.key == b'\n':
            if self.data:
                launch_app(self.data + self.complete, terminal=bool(msg.event.modifiers & yutani.Modifier.MOD_LEFT_SHIFT))
            self.close()
            return
        if msg.event.key == b'\b':
            if self.data:
                self.data = self.data[:-1]
                self.try_complete()
        else:
            self.data += msg.event.key.decode('utf-8')
            self.try_complete()
        self.draw()

    def match_icon(self):
        icons = {
            "calculator.py": "calculator",
            "clock-win": "clock",
            "file_browser.py": "file-browser",
            "make-it-snow": "snow",
            "game": "applications-simulation",
            "draw": "applications-painting",
            "about-applet.py": "star",
            "help-browser.py": "help",
            "terminal": "utilities-terminal",
        }
        x = (self.data+self.complete).split(" ")[0]
        if x in icons:
            return get_icon(icons[x],self.icon_width) # Odd names
        elif self.completed:
            return get_icon(x,self.icon_width) # Fallback
        return None

    def draw(self):
        surface = self.get_cairo_surface()
        ctx = cairo.Context(surface)

        ctx.set_operator(cairo.OPERATOR_SOURCE)
        ctx.rectangle(0,0,self.width,self.height)
        ctx.set_source_rgba(0,0,0,0)
        ctx.fill()

        ctx.set_operator(cairo.OPERATOR_OVER)
        rounded_rectangle(ctx,0,0,self.width,self.height,10)
        ctx.set_source_rgba(0,0,0,0.7)
        ctx.fill()

        icon = self.match_icon()
        if icon:

            ctx.save()
            ctx.translate(20,20)
            if icon.get_width() != self.icon_width:
                ctx.scale(self.icon_width/icon.get_width(),self.icon_width/icon.get_width())
            ctx.set_source_surface(icon,0,0)
            ctx.paint()
            ctx.restore()

        font = self.font
        tr = text_region.TextRegion(0,20,self.width,30,font=font)
        tr.set_one_line()
        tr.set_ellipsis()
        tr.set_alignment(2)
        tr.set_richtext(html.escape(self.data) + '<color 0x888888>' + html.escape(self.complete) + '</color>')
        tr.draw(self)


        self.flip()


def rounded_rectangle(ctx,x,y,w,h,r):
    degrees = math.pi / 180
    ctx.new_sub_path()

    ctx.arc(x + w - r, y + r, r, -90 * degrees, 0 * degrees)
    ctx.arc(x + w - r, y + h - r, r, 0 * degrees, 90 * degrees)
    ctx.arc(x + r, y + h - r, r, 90 * degrees, 180 * degrees)
    ctx.arc(x + r, y + r, r, 180 * degrees, 270 * degrees)
    ctx.close_path()

def launch_app(item,terminal=False):
    """Launch an application in the background."""
    if terminal:
        os.spawnvp(os.P_NOWAIT,'/bin/terminal',['terminal',item])
    else:
        os.spawnvp(os.P_NOWAIT,'/bin/sh',['/bin/sh','-c',item])

def logout_callback(item):
    """Request the active session be stopped."""
    yctx.session_end()

def finish_alt_tab(msg):
    """When Alt is released, call this to close the alt-tab window and focus the requested window."""
    global tabbing, new_focused, alttab

    w = windows_zorder[new_focused]
    yctx.focus_window(w.wid)
    tabbing = False
    new_focused = -1

    alttab.close()

def reload_wallpaper(signum, frame):
    """Respond to SIGUSR1 by reloading the wallpaper."""
    wallpaper.animate_new()

def alt_tab(msg):
    """When Alt+Tab or Alt+Shift+Tab are pressed, call this to set the active alt-tab window."""
    global tabbing, new_focused, alttab
    direction = 1 if (msg.event.modifiers & yutani.Modifier.MOD_LEFT_SHIFT) else -1
    if len(windows_zorder) < 1:
        return

    if tabbing:
        new_focused = new_focused + direction
    else:
        new_focused = len(windows_zorder) - 1 + direction
        alttab = AlttabWindow()

    if new_focused < 0:
        new_focused = len(windows_zorder)-1
    elif new_focused >= len(windows_zorder):
        new_focused = 0

    tabbing = True
    alttab.draw()

def set_binds():

    # Show terminal
    yctx.key_bind(ord('t'), yutani.Modifier.MOD_LEFT_CTRL | yutani.Modifier.MOD_LEFT_ALT, yutani.KeybindFlag.BIND_STEAL)

    # Application runner
    yctx.key_bind(yutani.Keycode.F2, yutani.Modifier.MOD_LEFT_ALT, yutani.KeybindFlag.BIND_STEAL)

    # Menu
    yctx.key_bind(yutani.Keycode.F1, yutani.Modifier.MOD_LEFT_ALT, yutani.KeybindFlag.BIND_STEAL)

    # Hide/show panel
    yctx.key_bind(yutani.Keycode.F11, yutani.Modifier.MOD_LEFT_CTRL, yutani.KeybindFlag.BIND_STEAL)

    # Alt-tab forward and backward
    yctx.key_bind(ord("\t"), yutani.Modifier.MOD_LEFT_ALT, yutani.KeybindFlag.BIND_STEAL)
    yctx.key_bind(ord("\t"), yutani.Modifier.MOD_LEFT_ALT | yutani.Modifier.MOD_LEFT_SHIFT, yutani.KeybindFlag.BIND_STEAL)
    # Release alt
    yctx.key_bind(yutani.Keycode.LEFT_ALT, 0, yutani.KeybindFlag.BIND_PASSTHROUGH)

def reset_zorder(signum, frame):
    wallpaper.set_stack(yutani.WindowStackOrder.ZORDER_BOTTOM)
    panel.set_stack(yutani.WindowStackOrder.ZORDER_TOP)
    set_binds()

if __name__ == '__main__':
    yctx = yutani.Yutani()

    appmenu = ApplicationsMenuWidget()
    widgets = [appmenu,WindowListWidget(),VolumeWidget(),DateWidget(),ClockWidget(),LogOutWidget()]
    panel = PanelWindow(widgets)

    wallpaper = WallpaperWindow()
    wallpaper.draw()

    app_runner = None

    # Tabbing
    tabbing = False
    alttab = None
    new_focused = -1

    yctx.timer_request(0,0)
    yctx.subscribe()

    set_binds()

    def update_window_list():
        yctx.query_windows()

        while 1:
            ad = yctx.wait_for(yutani.Message.MSG_WINDOW_ADVERTISE)
            if ad.size == 0:
                return

            yield ad


    windows_zorder = [x for x in update_window_list()]
    windows = sorted(windows_zorder, key=lambda window: window.wid)

    current_time = int(time.time())

    panel.draw()

    signal.signal(signal.SIGUSR1, reload_wallpaper)
    with open('/tmp/.wallpaper.pid','w') as f:
        f.write(str(os.getpid())+'\n')

    signal.signal(signal.SIGUSR2, reset_zorder)

    while 1:
        # Poll for events.
        msg = yutani.yutani_ctx.poll()
        if msg.type == yutani.Message.MSG_SESSION_END:
            # All applications should attempt to exit on SESSION_END.
            panel.close()
            wallpaper.close()
            break
        elif msg.type == yutani.Message.MSG_NOTIFY:
            # Update the window list.
            windows_zorder = [x for x in update_window_list()]
            windows = sorted(windows_zorder, key=lambda window: window.wid)
            panel.draw()
        elif msg.type == yutani.Message.MSG_TIMER_TICK:
            tick = int(time.time())
            if tick != current_time:
                try:
                    os.waitpid(-1,os.WNOHANG)
                except ChildProcessError:
                    pass
                current_time = tick
                panel.draw()
            if wallpaper.animations:
                wallpaper.animate()
        elif msg.type == yutani.Message.MSG_KEY_EVENT:
            if app_runner and msg.wid == app_runner.wid:
                app_runner.key_action(msg)
                continue
            if not app_runner and \
                (msg.event.modifiers & yutani.Modifier.MOD_LEFT_ALT) and \
                (msg.event.keycode == yutani.Keycode.F2) and \
                (msg.event.action == yutani.KeyAction.ACTION_DOWN):
                app_runner = ApplicationRunnerWindow()
                app_runner.draw()
            if not panel.menus and \
                (msg.event.modifiers & yutani.Modifier.MOD_LEFT_ALT) and \
                (msg.event.keycode == yutani.Keycode.F1) and \
                (msg.event.action == yutani.KeyAction.ACTION_DOWN):
                appmenu.activate()
            # Ctrl-Alt-T: Open Terminal
            if (msg.event.modifiers & yutani.Modifier.MOD_LEFT_CTRL) and \
                (msg.event.modifiers & yutani.Modifier.MOD_LEFT_ALT) and \
                (msg.event.keycode == ord('t')) and \
                (msg.event.action == yutani.KeyAction.ACTION_DOWN):
                launch_app('terminal')
            # Ctrl-F11: Toggle visibility of panel
            if (msg.event.modifiers & yutani.Modifier.MOD_LEFT_CTRL) and \
                (msg.event.keycode == yutani.Keycode.F11) and \
                (msg.event.action == yutani.KeyAction.ACTION_DOWN):
                panel.toggle_visibility()
            # Release alt while alt-tabbing
            if tabbing and (msg.event.keycode == 0 or msg.event.keycode == yutani.Keycode.LEFT_ALT) and \
                (msg.event.modifiers == 0) and (msg.event.action == yutani.KeyAction.ACTION_UP):
                finish_alt_tab(msg)
            # Alt-Tab and Alt-Shift-Tab: Switch window focus.
            if (msg.event.modifiers & yutani.Modifier.MOD_LEFT_ALT) and \
                (msg.event.keycode == ord("\t")) and \
                (msg.event.action == yutani.KeyAction.ACTION_DOWN):
                alt_tab(msg)
            if msg.wid in panel.menus:
                panel.menus[msg.wid].keyboard_event(msg)
        elif msg.type == yutani.Message.MSG_WELCOME:
            # Display size has changed.
            panel.resize(msg.display_width, PANEL_HEIGHT)
            wallpaper.resize(msg.display_width, msg.display_height)
        elif msg.type == yutani.Message.MSG_RESIZE_OFFER:
            # Resize the window.
            if msg.wid == panel.wid:
                panel.finish_resize(msg)
            elif msg.wid == wallpaper.wid:
                wallpaper.finish_resize(msg)
        elif msg.type == yutani.Message.MSG_WINDOW_MOUSE_EVENT:
            if msg.wid == panel.wid:
                panel.mouse_action(msg)
            elif msg.wid == wallpaper.wid:
                wallpaper.mouse_action(msg)
            if msg.wid in panel.menus:
                m = panel.menus[msg.wid]
                if msg.new_x >= 0 and msg.new_x < m.width and msg.new_y >= 0 and msg.new_y < m.height:
                    panel.hovered_menu = m
                elif panel.hovered_menu == m:
                    panel.hovered_menu = None
                m.mouse_action(msg)
        elif msg.type == yutani.Message.MSG_WINDOW_FOCUS_CHANGE:
            if msg.wid in panel.menus and msg.focused == 0:
                panel.menus[msg.wid].leave_menu()

