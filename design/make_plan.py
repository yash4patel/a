#!/usr/bin/env python3
"""Revised first-floor plan: attached bath, direct bedroom entry, store at stair."""

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.lib.colors import Color, white, black

OUT = "/agent/repos/a/design/FINAL_first_floor_revised_design.pdf"

PAGE = landscape(A3)  # 1190.55 x 841.89
W, H = PAGE

# colours
INK = Color(0.10, 0.10, 0.12)
WALL = Color(0.78, 0.76, 0.72)
WALL_E = Color(0.22, 0.20, 0.18)
NEW = Color(0.72, 0.12, 0.10)
NEW_FILL = Color(0.96, 0.86, 0.84)
WET = Color(0.78, 0.88, 0.92)
BAL = Color(0.93, 0.94, 0.90)
SIT = Color(0.97, 0.96, 0.93)
BED = Color(0.95, 0.93, 0.90)
STORE = Color(0.94, 0.91, 0.84)
PASS = Color(0.95, 0.95, 0.96)
BLUE = Color(0.15, 0.32, 0.48)
DIM = Color(0.25, 0.25, 0.28)
GREY = Color(0.35, 0.35, 0.38)

# geometry, feet, origin = inner north-west corner of sitting, +x east, +y south
EXT = 0.75
SIT_W = 16.0
PARTY = 0.75
BED_W = 14 + 4 / 12  # 14'-4"
X_P0 = SIT_W
X_P1 = SIT_W + PARTY
X_R1 = X_P1 + BED_W  # 31.0833

Y_BAL = 9.0
Y_BED0 = Y_BAL + EXT  # 9.75
Y_BED1 = 29.0
Y_STORE0 = 22.5
Y_WALL0 = 29.0
Y_WALL1 = 29.75
Y_LOW0 = 29.75
Y_LOW1 = 37.75  # 8'-0" stair / bath depth
Y_SOUTH_OUT = Y_LOW1 + EXT  # 38.5
BALC_D = 14.0

# store
ST_X0, ST_X1 = 7.5, 16.0
ST_WALL = 0.375

# bath 8'-6" x 8'-0"
BATH_W = 8.5
BX0 = X_R1 - BATH_W
BX1 = X_R1
BWALL = 0.375
PX1 = BX0 - BWALL  # passage east inner = west face of bath wall
# passage x X_P1 .. PX1

# openings
# sitting-bedroom door in party wall
DB_Y0, DB_Y1 = 13.6, 16.85  # 3'-3"
# store door
DS_X0, DS_X1 = 11.7, 14.95
# sitting entry from stair
DE_X0, DE_X1 = 1.4, 4.9  # 3'-6"
# stair to passage
DP_Y0, DP_Y1 = 30.35, 33.6
# bedroom to bath
DD_X0, DD_X1 = 23.15, 25.65  # 2'-6"
# common door bath west
DC_Y0, DC_Y1 = 32.15, 34.65
# balcony door from passage
DBAL_X0, DBAL_X1 = 17.85, 21.10
# SD bedroom to north balcony, 8'-0"
SD_X0 = X_P1 + (BED_W - 8.0) / 2
SD_X1 = SD_X0 + 8.0


def ft(v):
    v = float(v)
    sign = "-" if v < 0 else ""
    v = abs(v)
    feet = int(round(v * 12)) // 12
    inches = int(round(v * 12)) % 12
    if inches == 12:
        feet += 1
        inches = 0
    return f"{sign}{feet}'-{inches}\""


class Plan:
    def __init__(self, c, ox, oy, s):
        """ox, oy = PDF point of inner (0,0). +y in plan is south, so PDF y decreases."""
        self.c = c
        self.ox = ox
        self.oy = oy
        self.s = s

    def X(self, x):
        return self.ox + x * self.s

    def Y(self, y):
        return self.oy - y * self.s

    def rect(self, x, y, w, h, fill=None, stroke=INK, lw=0.8):
        self.c.saveState()
        if fill:
            self.c.setFillColor(fill)
        do_stroke = stroke is not None
        if do_stroke:
            self.c.setStrokeColor(stroke)
            self.c.setLineWidth(lw)
        # reportlab rect is from lower-left. Plan (x,y) is north-west of the rect,
        # plan y grows south, so PDF lower-left is (x, y+h)
        self.c.rect(self.X(x), self.Y(y + h), w * self.s, h * self.s, fill=1 if fill else 0, stroke=1 if do_stroke else 0)
        self.c.restoreState()

    def line(self, x1, y1, x2, y2, stroke=INK, lw=0.8, dash=None):
        self.c.saveState()
        self.c.setStrokeColor(stroke)
        self.c.setLineWidth(lw)
        if dash:
            self.c.setDash(dash)
        self.c.line(self.X(x1), self.Y(y1), self.X(x2), self.Y(y2))
        self.c.restoreState()

    def text(self, x, y, s, size=8, color=INK, align="c", font="Times-Bold"):
        self.c.saveState()
        self.c.setFillColor(color)
        self.c.setFont(font, size)
        px, py = self.X(x), self.Y(y)
        if align == "c":
            self.c.drawCentredString(px, py, s)
        elif align == "l":
            self.c.drawString(px, py, s)
        else:
            self.c.drawRightString(px, py, s)
        self.c.restoreState()

    def wall(self, x, y, w, h):
        self.rect(x, y, w, h, fill=WALL, stroke=WALL_E, lw=0.9)
        # light hatch
        self.c.saveState()
        p = self.c.beginPath()
        p.rect(self.X(x), self.Y(y + h), w * self.s, h * self.s)
        self.c.clipPath(p, stroke=0, fill=0)
        self.c.setStrokeColor(Color(0.55, 0.52, 0.48))
        self.c.setLineWidth(0.3)
        step = 4.5
        x0, x1 = self.X(x) - h * self.s, self.X(x + w) + h * self.s
        y0, y1 = self.Y(y + h), self.Y(y)
        n = int((x1 - x0 + (y0 - y1)) / step) + 2
        for i in range(-2, n):
            xa = x0 + i * step
            self.c.line(xa, y0, xa + (y0 - y1), y1)
        self.c.restoreState()

    def window(self, x1, y1, x2, y2, horizontal=True):
        """Glass line inside a wall opening. Coordinates are the opening ends."""
        if horizontal:
            # opening along x at wall spanning y1-y2; draw at mid
            ym = (y1 + y2) / 2
            self.line(x1, ym - 0.06, x2, ym - 0.06, lw=0.7)
            self.line(x1, ym + 0.06, x2, ym + 0.06, lw=0.7)
            self.line(x1, y1, x1, y2, lw=0.6)
            self.line(x2, y1, x2, y2, lw=0.6)
        else:
            xm = (x1 + x2) / 2
            self.line(xm - 0.06, y1, xm - 0.06, y2, lw=0.7)
            self.line(xm + 0.06, y1, xm + 0.06, y2, lw=0.7)
            self.line(x1, y1, x2, y1, lw=0.6)
            self.line(x1, y2, x2, y2, lw=0.6)

    def door(self, hinge_x, hinge_y, width, closed, opened, new=False):
        """Leaf opens from `closed` direction to `opened` direction.
        Directions are plan directions: n/s/e/w, with y increasing south.
        The arc is the quarter-circle a person walks.
        """
        import math
        col = NEW if new else INK
        vec = {"e": (1, 0), "w": (-1, 0), "s": (0, 1), "n": (0, -1)}
        cdx, cdy = vec[closed]
        odx, ody = vec[opened]
        self.line(hinge_x, hinge_y, hinge_x + odx * width, hinge_y + ody * width, stroke=col, lw=1.05)
        a0 = math.atan2(cdy, cdx)
        a1 = math.atan2(ody, odx)
        sweep = a1 - a0
        while sweep <= -math.pi:
            sweep += 2 * math.pi
        while sweep > math.pi:
            sweep -= 2 * math.pi
        steps = 14
        pts = []
        for i in range(steps + 1):
            a = a0 + sweep * i / steps
            pts.append((hinge_x + width * math.cos(a), hinge_y + width * math.sin(a)))
        for i in range(len(pts) - 1):
            self.line(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1], stroke=col, lw=0.55, dash=(1.2, 1.3))
        self.c.saveState()
        self.c.setFillColor(col)
        self.c.circle(self.X(hinge_x), self.Y(hinge_y), 1.15, fill=1, stroke=0)
        self.c.restoreState()

    def dim(self, x1, y1, x2, y2, label, offset=0.0, along="h"):
        """Dimension parallel to the segment, offset to the left of direction x1->x2, y1->y2
        in plan coords (y south). offset positive pushes to the right of travel? We'll pass explicit.
        along 'h' means horizontal dim (constant y), label above/below via offset in plan y.
        along 'v' constant x, offset in plan x.
        """
        self.c.saveState()
        self.c.setStrokeColor(DIM)
        self.c.setFillColor(DIM)
        self.c.setLineWidth(0.45)
        if along == "h":
            y = y1 + offset
            self.c.line(self.X(x1), self.Y(y), self.X(x2), self.Y(y))
            for x in (x1, x2):
                self.c.line(self.X(x), self.Y(y) - 3, self.X(x), self.Y(y) + 3)
                # extension
                self.c.setStrokeColor(Color(0.6, 0.6, 0.62))
                self.c.line(self.X(x), self.Y(y1), self.X(x), self.Y(y))
                self.c.setStrokeColor(DIM)
            self.c.setFont("Times-Roman", 7)
            self.c.drawCentredString((self.X(x1) + self.X(x2)) / 2, self.Y(y) + 3, label)
        else:
            x = x1 + offset
            self.c.line(self.X(x), self.Y(y1), self.X(x), self.Y(y2))
            for y in (y1, y2):
                self.c.line(self.X(x) - 3, self.Y(y), self.X(x) + 3, self.Y(y))
                self.c.setStrokeColor(Color(0.6, 0.6, 0.62))
                self.c.line(self.X(x1), self.Y(y), self.X(x), self.Y(y))
                self.c.setStrokeColor(DIM)
            self.c.saveState()
            self.c.translate(self.X(x) - 3, (self.Y(y1) + self.Y(y2)) / 2)
            self.c.rotate(90)
            self.c.setFont("Times-Roman", 7)
            self.c.drawCentredString(0, 0, label)
            self.c.restoreState()
        self.c.restoreState()


def draw_floor(c):
    s = 11.15  # pt per foot
    # inner 0,0 near top-left of plan
    ox, oy = 78, H - 78
    p = Plan(c, ox, oy, s)

    # floors
    p.rect(0, 0, SIT_W, Y_STORE0, fill=SIT, stroke=None, lw=0)
    p.rect(0, Y_STORE0, 7.5, Y_WALL0 - Y_STORE0, fill=SIT, stroke=None, lw=0)
    p.rect(ST_X0, Y_STORE0 + ST_WALL, ST_X1 - ST_X0, Y_WALL0 - Y_STORE0 - ST_WALL, fill=STORE, stroke=None, lw=0)
    p.rect(X_P1, 0, BED_W, Y_BAL, fill=BAL, stroke=None, lw=0)
    p.rect(X_P1, Y_BED0, BED_W, Y_BED1 - Y_BED0, fill=BED, stroke=None, lw=0)
    p.rect(X_P1, Y_LOW0, PX1 - X_P1, Y_LOW1 - Y_LOW0, fill=PASS, stroke=None, lw=0)
    p.rect(BX0, Y_LOW0, BATH_W, Y_LOW1 - Y_LOW0, fill=white, stroke=None, lw=0)
    # wet zone south 3'-3" of bath
    p.rect(BX0, 34.5, BATH_W, Y_LOW1 - 34.5, fill=WET, stroke=None, lw=0)
    p.rect(0, Y_LOW0, SIT_W, Y_LOW1 - Y_LOW0, fill=Color(0.96, 0.96, 0.97), stroke=None, lw=0)
    p.rect(-EXT, Y_SOUTH_OUT, X_R1 + EXT + EXT, BALC_D, fill=BAL, stroke=None, lw=0)

    # redraw stair floor over the fill (already white-ish)
    # walls
    # outer west
    p.wall(-EXT, -EXT, EXT, Y_SOUTH_OUT + EXT)
    # outer north sitting only
    p.wall(-EXT, -EXT, X_P1 + EXT, EXT)
    # outer east full enclosed
    p.wall(X_R1, -EXT, EXT, Y_SOUTH_OUT + EXT)
    # south external wall of enclosed block
    p.wall(-EXT, Y_LOW1, X_R1 + 2 * EXT, EXT)
    # punch balcony door later by covering with floor and jambs — draw opening as gap
    # We'll draw south wall in three pieces
    # Actually already drew full wall. Cover the door opening with balcony colour and jambs.
    p.rect(DBAL_X0, Y_LOW1, DBAL_X1 - DBAL_X0, EXT, fill=BAL, stroke=None, lw=0)

    # party wall pieces
    p.wall(X_P0, 0, PARTY, DB_Y0)  # above bedroom door, includes beside balcony
    p.wall(X_P0, DB_Y1, PARTY, Y_STORE0 - DB_Y1)
    # store east is party, from store north wall to stair wall
    p.wall(X_P0, Y_STORE0, PARTY, Y_WALL0 - Y_STORE0)
    # party at stair, with passage opening
    p.wall(X_P0, Y_LOW0, PARTY, DP_Y0 - Y_LOW0)
    p.wall(X_P0, DP_Y1, PARTY, Y_LOW1 - DP_Y1)

    # balcony / bedroom wall with SD opening
    p.wall(X_P1, Y_BAL, SD_X0 - X_P1, EXT)
    p.wall(SD_X1, Y_BAL, X_R1 - SD_X1, EXT)

    # bedroom south wall over the passage (west part) full, and over bath with door
    p.wall(X_P1, Y_WALL0, PX1 - X_P1, EXT)  # over passage, solid (passage is entered from stair)
    p.wall(BX0, Y_WALL0, DD_X0 - BX0, EXT)
    p.wall(DD_X1, Y_WALL0, BX1 - DD_X1, EXT)

    # bath west wall with common door
    p.wall(PX1, Y_LOW0, BWALL, DC_Y0 - Y_LOW0)
    p.wall(PX1, DC_Y1, BWALL, Y_LOW1 - DC_Y1)

    # store partitions (new)
    p.wall(ST_X0, Y_STORE0, ST_WALL, Y_WALL0 - Y_STORE0)
    p.wall(ST_X0, Y_STORE0, ST_X1 - ST_X0, ST_WALL)
    # store south wall is structural 9" with door — draw as part of the big cross wall
    p.wall(0, Y_WALL0, DE_X0, EXT)
    p.wall(DE_X1, Y_WALL0, DS_X0 - DE_X1, EXT)
    p.wall(DS_X1, Y_WALL0, SIT_W - DS_X1, EXT)

    # north balcony side return at west already party; east already outer
    # railing north of balcony
    p.line(X_P1, 0, X_R1 + EXT, 0, lw=1.1)
    # railing posts
    x = X_P1
    while x <= X_R1 + EXT:
        p.line(x, -0.15, x, 0.15, lw=0.7)
        x += 1.15
    # front balcony railings
    p.line(-EXT, Y_SOUTH_OUT + BALC_D, X_R1 + EXT, Y_SOUTH_OUT + BALC_D, lw=1.15)
    p.line(-EXT, Y_SOUTH_OUT, -EXT, Y_SOUTH_OUT + BALC_D, lw=1.0)
    p.line(X_R1 + EXT, Y_SOUTH_OUT, X_R1 + EXT, Y_SOUTH_OUT + BALC_D, lw=1.0)
    xx = -EXT
    while xx <= X_R1 + EXT:
        p.line(xx, Y_SOUTH_OUT + BALC_D - 0.18, xx, Y_SOUTH_OUT + BALC_D + 0.12, lw=0.6)
        xx += 1.2

    # windows
    p.window(3.5, -EXT, 12.5, 0, horizontal=True)  # W_big
    p.window(-EXT, 3.2, 0, 8.2, horizontal=False)
    p.window(-EXT, 12.4, 0, 17.4, horizontal=False)
    p.window(X_R1, 16.6, X_R1 + EXT, 21.6, horizontal=False)  # bed W
    p.window(X_R1, 33.3, X_R1 + EXT, 35.3, horizontal=False)  # vent

    # sliding door panels in SD opening
    for i in range(4):
        xa = SD_X0 + i * 2.0
        p.line(xa, Y_BAL, xa, Y_BAL + EXT, lw=0.5)
    p.line(SD_X0, Y_BAL + EXT / 2, SD_X1, Y_BAL + EXT / 2, lw=0.8)

    # doors: hinge, width, closed-leaf direction, open-leaf direction
    # sitting to bedroom — opens east into the bedroom
    p.door(X_P1, DB_Y0, DB_Y1 - DB_Y0, "s", "e", new=True)
    # store door — opens north into the store
    p.door(DS_X0, Y_WALL0, DS_X1 - DS_X0, "e", "n", new=True)
    # stair to sitting — opens north into the sitting room
    p.door(DE_X0, Y_WALL0, DE_X1 - DE_X0, "e", "n", new=False)
    # stair to passage — opens east into the passage
    p.door(X_P1, DP_Y0, DP_Y1 - DP_Y0, "s", "e", new=False)
    # bedroom to bath — opens south into the bathroom
    p.door(DD_X0, Y_WALL1, DD_X1 - DD_X0, "e", "s", new=True)
    # common bath door — opens east into the bathroom
    p.door(BX0, DC_Y0, DC_Y1 - DC_Y0, "s", "e", new=True)
    # balcony door — opens north into the passage
    p.door(DBAL_X0, Y_LOW1, DBAL_X1 - DBAL_X0, "e", "n", new=False)

    # stair symbol
    import math
    # flight from x 0.4 to 11.6, landing 11.6 to 16
    p.line(11.6, Y_LOW0 + 0.15, 11.6, Y_LOW1 - 0.15, lw=0.7)
    p.text(13.9, 35.15, "LANDING", size=6.5, font="Times-Bold", color=GREY)
    p.text(13.9, 35.8, "UP", size=8, font="Times-Bold", color=NEW)
    # arrival is this east landing; travel on the flight is toward the east
    p.line(12.35, 35.45, 15.15, 35.45, stroke=NEW, lw=1.0)
    p.line(15.15, 35.45, 14.55, 35.1, stroke=NEW, lw=1.0)
    p.line(15.15, 35.45, 14.55, 35.8, stroke=NEW, lw=1.0)
    # treads
    for i in range(12):
        x = 0.55 + i * (11.0 / 11)
        p.line(x, Y_LOW0 + 0.25, x, Y_LOW1 - 0.25, stroke=Color(0.45, 0.45, 0.48), lw=0.45)
    # DN arrow toward west
    p.line(10.4, 34.6, 2.2, 34.6, stroke=INK, lw=1.0)
    p.line(2.2, 34.6, 2.9, 34.25, lw=1.0)
    p.line(2.2, 34.6, 2.9, 34.95, lw=1.0)
    p.text(6.2, 34.15, "DN", size=8, font="Times-Bold")
    p.text(6.3, 36.55, "STAIR", size=8, font="Times-Bold")
    p.text(6.3, 37.25, "TO GROUND FLOOR", size=6, font="Times-Italic", color=GREY)

    # dashed link: store is what you face
    p.line(13.3, 34.7, 13.3, Y_WALL1 + 0.2, stroke=NEW, lw=0.7, dash=(2, 1.5))

    # fixtures in bath — basin on north wall
    # basin 2'-0" x 1'-6"
    p.rect(27.15, Y_LOW0, 2.05, 1.45, fill=white, stroke=BLUE, lw=1.0)
    p.c.saveState()
    p.c.setStrokeColor(BLUE)
    p.c.setLineWidth(0.8)
    p.c.ellipse(p.X(27.35), p.Y(Y_LOW0 + 1.25), p.X(29.0), p.Y(Y_LOW0 + 0.25), fill=0, stroke=1)
    p.c.setFillColor(BLUE)
    p.c.circle(p.X(28.15), p.Y(Y_LOW0 + 0.35), 1.3, fill=1, stroke=0)
    p.c.restoreState()
    p.text(26.15, 30.45, "W.B.", size=6.5, font="Times-Bold", color=NEW)

    # WC on east wall
    p.c.saveState()
    p.c.setStrokeColor(INK)
    p.c.setFillColor(white)
    p.c.setLineWidth(0.8)
    # tank against east wall
    p.rect(BX1 - 0.55, 34.55, 0.55, 1.7, fill=white, stroke=INK, lw=0.7)
    p.c.ellipse(p.X(BX1 - 2.15), p.Y(36.45), p.X(BX1 - 0.45), p.Y(34.4), fill=0, stroke=1)
    p.c.restoreState()
    p.text(BX1 - 1.35, 33.85, "W.C.", size=6.5, font="Times-Bold")

    # shower / wet label
    p.text(26.7, 36.15, "SHOWER", size=6.5, font="Times-Bold", color=BLUE)
    p.text(26.7, 36.75, "WET FLOOR", size=5.5, font="Times-Italic", color=BLUE)
    # floor drain
    p.c.saveState()
    p.c.setStrokeColor(BLUE)
    p.c.setLineWidth(0.6)
    p.c.circle(p.X(29.4), p.Y(36.5), 2.2, fill=0, stroke=1)
    p.c.line(p.X(29.4) - 2.2, p.Y(36.5), p.X(29.4) + 2.2, p.Y(36.5))
    p.c.line(p.X(29.4), p.Y(36.5) - 2.2, p.X(29.4), p.Y(36.5) + 2.2)
    p.c.restoreState()

    # bed, clear of the new west door and of the bathroom door
    p.rect(X_P1 + 5.4, 15.2, 6.4, 4.6, fill=white, stroke=Color(0.55, 0.5, 0.45), lw=0.7)
    p.rect(X_P1 + 5.4, 15.2, 0.42, 4.6, fill=Color(0.85, 0.82, 0.78), stroke=Color(0.55, 0.5, 0.45), lw=0.5)
    p.text(X_P1 + 9.0, 17.6, "BED", size=6.5, font="Times-Italic", color=GREY)
    # wardrobe along west wall, south of the sitting door
    p.rect(X_P1, 18.6, 1.85, 9.6, fill=Color(0.90, 0.84, 0.74), stroke=Color(0.45, 0.35, 0.22), lw=0.7)
    p.text(X_P1 + 0.92, 22.9, "WARD", size=5.5, font="Times-Bold", color=Color(0.35, 0.25, 0.15))
    p.text(X_P1 + 0.92, 23.5, "ROBE", size=5.5, font="Times-Bold", color=Color(0.35, 0.25, 0.15))

    # sofa hint in sitting
    p.rect(1.2, 8.5, 2.2, 6.5, fill=white, stroke=Color(0.6, 0.58, 0.55), lw=0.6)
    p.rect(3.2, 8.8, 5.5, 2.1, fill=white, stroke=Color(0.6, 0.58, 0.55), lw=0.6)
    p.text(5.6, 7.6, "SOFA", size=6, font="Times-Italic", color=GREY)

    # store shelves
    p.line(ST_X0 + ST_WALL, Y_STORE0 + ST_WALL + 1.15, ST_X1 - 0.15, Y_STORE0 + ST_WALL + 1.15, stroke=Color(0.45, 0.38, 0.22), lw=0.6)
    p.text(9.3, 26.7, "SHELVES", size=6, font="Times-Italic", color=GREY)

    # room labels
    p.text(8.0, 4.3, "SITTING ROOM", size=11, font="Times-Bold")
    p.text(8.0, 5.35, "16'-0\"  x  22'-6\"", size=8, font="Times-Roman")
    p.text(3.6, 25.6, "TO STAIR", size=6, font="Times-Italic", color=GREY)

    p.text(11.7, 23.7, "STORE ROOM", size=8, font="Times-Bold", color=NEW)
    p.text(11.7, 24.45, "8'-6\" x 6'-6\"", size=7, font="Times-Roman", color=NEW)
    p.text(11.7, 25.15, "IN FRONT OF STAIR", size=6.2, font="Times-Bold", color=NEW)

    p.text(X_P1 + BED_W / 2, 3.3, "BALCONY", size=9, font="Times-Bold")
    p.text(X_P1 + BED_W / 2, 4.15, "14'-4\" x 9'-0\"", size=7.5, font="Times-Roman")

    p.text(X_P1 + 8.9, 11.55, "BED ROOM", size=11, font="Times-Bold")
    p.text(X_P1 + 8.9, 12.5, "14'-4\"  x  19'-3\"", size=8, font="Times-Roman")

    p.text((X_P1 + PX1) / 2, 35.55, "PASSAGE", size=7, font="Times-Bold", color=GREY)

    p.text(27.3, 32.85, "BATH", size=7.5, font="Times-Bold")
    p.text(27.3, 33.5, "8'-6\" x 8'-0\"", size=6, font="Times-Roman")

    p.text(( -EXT + X_R1 + EXT) / 2, Y_SOUTH_OUT + 6.2, "FRONT BALCONY", size=11, font="Times-Bold")
    p.text(( -EXT + X_R1 + EXT) / 2, Y_SOUTH_OUT + 7.15, "FULL WIDTH  x  14'-0\"", size=8, font="Times-Roman")

    # new-work tags
    p.text(X_P0 - 0.35, 12.7, "NEW DOOR", size=5.4, font="Times-Bold", color=NEW, align="r")
    p.text(X_P0 - 0.35, 13.25, "FROM SITTING", size=5.2, font="Times-Bold", color=NEW, align="r")
    p.text(27.6, 28.15, "FROM BED", size=5.2, font="Times-Bold", color=NEW)

    # window tags
    p.text(8.0, 1.15, "W_big   9'-0\" x 4'-6\"", size=6, font="Times-Italic", color=GREY)
    p.text(X_R1 + 0.15, 15.7, "W", size=6.5, font="Times-Bold", align="l")
    p.text(X_R1 + 0.15, 32.55, "V", size=6.5, font="Times-Bold", align="l")
    p.text(SD_X0 + 4, Y_BAL - 0.45, "SD  8'-0\" x 7'-0\"  (4 PANEL)", size=6, font="Times-Italic", color=GREY)

    # dimensions
    p.dim(-EXT, -EXT, X_R1 + EXT, -EXT, "32'-7\"  OVERALL", offset=-1.15, along="h")
    p.dim(0, 0, 16, 0, "16'-0\"", offset=-0.55, along="h")
    p.dim(X_P1, 0, X_R1, 0, "14'-4\"", offset=-0.55, along="h")
    p.dim(-EXT, -EXT, -EXT, Y_SOUTH_OUT, "39'-3\"", offset=-1.35, along="v")
    p.dim(0, 0, 0, Y_STORE0, "22'-6\"", offset=-0.7, along="v")
    p.dim(0, Y_STORE0, 0, Y_WALL0, "6'-6\"", offset=-0.7, along="v")
    p.dim(X_R1, Y_BED0, X_R1, Y_BED1, "19'-3\"", offset=1.15, along="v")
    p.dim(X_R1, Y_LOW0, X_R1, Y_LOW1, "8'-0\"", offset=1.15, along="v")
    p.dim(X_R1, 0, X_R1, Y_BAL, "9'-0\"", offset=1.15, along="v")

    # north arrow
    nx, ny = p.X(X_R1 + 2.4), p.Y(8.5)
    c.saveState()
    c.setFillColor(INK)
    c.setStrokeColor(INK)
    c.setLineWidth(1)
    path = c.beginPath()
    path.moveTo(nx, ny)
    path.lineTo(nx - 7, ny - 22)
    path.lineTo(nx, ny - 16)
    path.lineTo(nx + 7, ny - 22)
    path.close()
    c.drawPath(path, fill=1, stroke=0)
    c.setFont("Times-Bold", 11)
    c.drawCentredString(nx, ny + 6, "N")
    c.restoreState()

    # scale bar
    c.setStrokeColor(INK)
    c.setFillColor(INK)
    c.setLineWidth(1)
    bx, by = 70, 48
    c.line(bx, by, bx + 4 * s, by)
    for i in range(5):
        c.line(bx + i * s, by - 3, bx + i * s, by + 3)
    c.setFont("Times-Roman", 7)
    c.drawCentredString(bx + 2 * s, by + 6, "SCALE  1:100    (1 ft grid ticks)")
    c.setFont("Times-Italic", 7)
    c.drawString(bx - 2, by - 16, "0        1 ft        2 ft        3 ft        4 ft")

    # title block on the right
    tb_x = 560
    c.setStrokeColor(INK)
    c.setLineWidth(1.2)
    c.rect(tb_x, 36, W - tb_x - 28, H - 64, stroke=1, fill=0)
    c.setFillColor(Color(0.16, 0.16, 0.18))
    c.rect(tb_x, H - 118, W - tb_x - 28, 54, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Times-Bold", 11)
    c.drawString(tb_x + 12, H - 84, "REVISED FIRST FLOOR PLAN")
    c.setFont("Times-Roman", 8)
    c.drawString(tb_x + 12, H - 100, "PROPOSED RESIDENCE  ·  DR. YEDHENAI PATEL")
    c.setFillColor(INK)
    c.setFont("Times-Bold", 9)
    y = H - 140
    c.drawString(tb_x + 12, y, "WHAT CHANGED")
    y -= 16
    notes = [
        ("1", "Bedroom opens directly off the sitting room.", "New 3'-3\" door in the common wall. You no longer walk through the corridor to reach the bed."),
        ("2", "Bathroom is attached to the bedroom.", "New 2'-6\" door in the bedroom's south wall. The old store that sat between them is removed."),
        ("3", "Store room is in front of the stair.", "8'-6\" x 6'-6\", door facing the upper landing. This is the first door you meet as you come up."),
        ("4", "Wash basin is inside the bathroom.", "On the north wall, dry side, beside the bedroom door. The old basin in the passage is removed."),
    ]
    c.setFont("Times-Roman", 8)
    for num, title, body in notes:
        c.setFillColor(NEW)
        c.setFont("Times-Bold", 9)
        c.drawString(tb_x + 12, y, num)
        c.setFillColor(INK)
        c.drawString(tb_x + 26, y, title)
        y -= 12
        c.setFont("Times-Roman", 7.5)
        c.setFillColor(GREY)
        # wrap body
        words = body.split()
        line = ""
        for w in words:
            trial = (line + " " + w).strip()
            if c.stringWidth(trial, "Times-Roman", 7.5) > 250:
                c.drawString(tb_x + 26, y, line)
                y -= 10
                line = w
            else:
                line = trial
        if line:
            c.drawString(tb_x + 26, y, line)
            y -= 14
        y -= 4

    y -= 4
    c.setFillColor(INK)
    c.setFont("Times-Bold", 9)
    c.drawString(tb_x + 12, y, "WASH BASIN")
    y -= 12
    c.setFont("Times-Roman", 7.5)
    c.setFillColor(GREY)
    basin_txt = (
        "Placed on the north wall of the bathroom, clear of the shower. "
        "That wall is the dry side next to the new bedroom door. "
        "The tiled wet walls, the wall-hung W.C. and the raised wet floor stay where they are. "
        "Basin 24 inch, mirror above, bottle trap inside the bathroom. "
        "Do not put the basin back in the passage."
    )
    words = basin_txt.split()
    line = ""
    for w in words:
        trial = (line + " " + w).strip()
        if c.stringWidth(trial, "Times-Roman", 7.5) > 250:
            c.drawString(tb_x + 12, y, line)
            y -= 10
            line = w
        else:
            line = trial
    if line:
        c.drawString(tb_x + 12, y, line)
        y -= 16

    c.setFillColor(INK)
    c.setFont("Times-Bold", 9)
    c.drawString(tb_x + 12, y, "OPENINGS")
    y -= 4
    c.setStrokeColor(Color(0.7, 0.7, 0.72))
    c.line(tb_x + 12, y, tb_x + 270, y)
    y -= 12
    rows = [
        ("D", "3'-3\" x 7'-0\"", "Sitting, store, balcony, passage"),
        ("D1", "2'-6\" x 7'-0\"", "Both bathroom doors"),
        ("SD", "8'-0\" x 7'-0\"", "Bedroom to north balcony, 4-panel"),
        ("W_big", "9'-0\" x 4'-6\"", "Sitting room, north wall"),
        ("W", "5'-0\" x 4'-0\"", "Sitting west, bedroom east"),
        ("V", "2'-0\" x 2'-6\"", "Bathroom east wall, above W.C."),
    ]
    for a, b, d in rows:
        c.setFont("Times-Bold", 7.5)
        c.setFillColor(INK)
        c.drawString(tb_x + 12, y, a)
        c.setFont("Times-Roman", 7.5)
        c.drawString(tb_x + 48, y, b)
        c.setFillColor(GREY)
        c.drawString(tb_x + 125, y, d)
        y -= 11

    y -= 8
    c.setFillColor(NEW)
    c.setFont("Times-Bold", 8)
    c.drawString(tb_x + 12, y, "RED  =  new door, new store, new basin")
    y -= 14
    c.setFillColor(INK)
    c.setFont("Times-Bold", 9)
    c.drawString(tb_x + 12, y, "SITE NOTE")
    y -= 12
    c.setFillColor(GREY)
    c.setFont("Times-Roman", 7.5)
    site = (
        "External walls, stair, both balconies, bedroom east window and the bathroom W.C. stay. "
        "The new sitting-to-bedroom opening is in the 9 inch wall: provide an R.C.C. lintel and confirm there is no column in that bay before cutting. "
        "Common bathroom door is kept so guests can reach the only toilet without crossing the bed. Bolt it from the bathroom side if the room is in use."
    )
    words = site.split()
    line = ""
    for w in words:
        trial = (line + " " + w).strip()
        if c.stringWidth(trial, "Times-Roman", 7.5) > 255:
            c.drawString(tb_x + 12, y, line)
            y -= 10
            line = w
        else:
            line = trial
    if line:
        c.drawString(tb_x + 12, y, line)
        y -= 16

    c.setFillColor(INK)
    c.setFont("Times-Italic", 7.5)
    c.drawString(tb_x + 12, y, "Sheet 01 of 02    ·    First floor    ·    Not for construction until checked on site")

    # sheet title top
    c.setFillColor(INK)
    c.setFont("Times-Bold", 10)
    c.drawString(36, H - 32, "01  —  REVISED 2D FIRST FLOOR PLAN")
    c.setFont("Times-Italic", 8)
    c.setFillColor(GREY)
    c.drawString(280, H - 32, "Attached bathroom  ·  Direct bedroom from sitting  ·  Store in front of stair")


def draw_bath_sheet(c):
    c.setFillColor(INK)
    c.setFont("Times-Bold", 10)
    c.drawString(36, H - 32, "02  —  BATHROOM DETAIL  AND  HOW TO WALK THE FLOOR")
    c.setFont("Times-Italic", 8)
    c.setFillColor(GREY)
    c.drawString(430, H - 32, "Wash basin fixed on the dry wall beside the bedroom door")

    # enlarged bath, 1 ft = 36 pt
    s = 34
    ox, oy = 120, H - 128
    p = Plan(c, ox, oy, s)
    # local coords 0..8.5 x, 0..8 y  (bath only), y south
    bw, bd = 8.5, 8.0

    p.rect(0, 0, bw, bd, fill=white, stroke=None, lw=0)
    p.rect(0, 4.15, bw, bd - 4.15, fill=WET, stroke=None, lw=0)

    p.wall(-EXT, -EXT, bw + 2 * EXT, EXT)  # north, with door gap drawn over
    p.wall(-EXT, bd, bw + 2 * EXT, EXT)  # south
    p.wall(-EXT, 0, EXT, bd)  # west with door gap
    p.wall(bw, 0, EXT, bd)  # east

    # door from bedroom on north, local x 0.55 to 3.05
    p.rect(0.55, -EXT, 2.5, EXT, fill=BED, stroke=None, lw=0)
    # common door on west, local y 2.4 to 4.9
    p.rect(-EXT, 2.4, EXT, 2.5, fill=PASS, stroke=None, lw=0)

    # redraw jambs by walls already full — cover done. Add jamb lines
    p.line(0.55, -EXT, 0.55, 0, lw=1.0)
    p.line(3.05, -EXT, 3.05, 0, lw=1.0)
    p.line(-EXT, 2.4, 0, 2.4, lw=1.0)
    p.line(-EXT, 4.9, 0, 4.9, lw=1.0)

    p.door(0.55, 0, 2.5, "e", "s", new=True)
    p.door(0, 2.4, 2.5, "s", "e", new=True)

    # basin on north wall, local x 5.3 to 7.3, projection 1.5
    p.rect(5.25, 0, 2.1, 1.55, fill=white, stroke=BLUE, lw=1.4)
    c.saveState()
    c.setStrokeColor(BLUE)
    c.setLineWidth(1.1)
    c.ellipse(p.X(5.5), p.Y(1.3), p.X(7.15), p.Y(0.28), fill=0, stroke=1)
    c.setFillColor(BLUE)
    c.circle(p.X(6.3), p.Y(0.38), 2.4, fill=1, stroke=0)
    c.restoreState()
    # mirror
    p.line(5.35, -0.28, 7.25, -0.28, stroke=BLUE, lw=2.0)

    # WC east
    p.rect(bw - 0.7, 4.55, 0.7, 1.85, fill=white, stroke=INK, lw=1)
    c.saveState()
    c.setStrokeColor(INK)
    c.setLineWidth(1)
    c.ellipse(p.X(bw - 2.35), p.Y(6.6), p.X(bw - 0.55), p.Y(4.4), fill=0, stroke=1)
    c.restoreState()

    # vent
    p.window(bw, 4.7, bw + EXT, 6.7, horizontal=False)

    # shower mixer on south wall
    p.line(3.2, bd - 0.15, 5.4, bd - 0.15, stroke=BLUE, lw=2)
    c.saveState()
    c.setStrokeColor(BLUE)
    c.setLineWidth(0.8)
    c.circle(p.X(6.6), p.Y(6.7), 5, fill=0, stroke=1)
    c.line(p.X(6.6) - 5, p.Y(6.7), p.X(6.6) + 5, p.Y(6.7))
    c.line(p.X(6.6), p.Y(6.7) - 5, p.X(6.6), p.Y(6.7) + 5)
    c.restoreState()

    # labels inside
    p.text(6.3, 2.15, "WASH BASIN", size=9, font="Times-Bold", color=NEW)
    p.text(6.3, 2.7, "24\"  on north wall", size=7, font="Times-Roman", color=NEW)
    p.text(1.55, 1.55, "DOOR FROM", size=6.5, font="Times-Bold", color=NEW)
    p.text(1.55, 2.05, "BEDROOM", size=6.5, font="Times-Bold", color=NEW)
    p.text(bw - 1.5, 4.15, "W.C.", size=8, font="Times-Bold")
    p.text(bw + 0.2, 5.5, "V", size=8, font="Times-Bold", align="l")
    p.text(4.2, 6.55, "SHOWER  ·  WET FLOOR", size=8, font="Times-Bold", color=BLUE)
    p.text(6.6, 7.35, "F.D.", size=7, font="Times-Bold", color=BLUE)
    p.text(-1.05, 3.7, "COMMON", size=7, font="Times-Bold", color=NEW, align="r")
    p.text(-1.05, 4.25, "DOOR", size=7, font="Times-Bold", color=NEW, align="r")
    p.text(bw / 2, -1.35, "NORTH    BEDROOM SIDE    DRY", size=8, font="Times-Bold")
    p.text(bw / 2, bd + 1.05, "SOUTH   WET FLOOR", size=8, font="Times-Bold", color=BLUE)

    p.text(bw / 2, bd + 2.05, "BATHROOM   8'-6\"  x  8'-0\"      SCALE 1:40", size=8, font="Times-Roman")

    # why this wall, to the right of the detail
    tx = 470
    c.setFillColor(INK)
    c.setFont("Times-Bold", 12)
    c.drawString(tx, H - 100, "Where the wash basin goes")
    c.setStrokeColor(NEW)
    c.setLineWidth(1.5)
    c.line(tx, H - 108, tx + 220, H - 108)

    bullets = [
        ("On the north wall, dry side.",
         "You walk in from the bedroom and the basin is on the same wall, to the right of that door. Hands are washed before you step back into the bedroom."),
        ("Clear of the shower.",
         "The raised wet floor and the shower stay on the south side, where the taps already are. Water does not spray the mirror."),
        ("Clear of the W.C.",
         "The wall-hung W.C. stays on the east wall, under the existing ventilator. Nothing already fixed there has to move."),
        ("Not in the passage.",
         "The old drawing put the basin outside the bathroom door. That is removed. Guests and the bedroom both use the basin inside the room."),
        ("Common door stays.",
         "This is the only toilet on the floor. A second 2'-6\" door opens from the passage so the sitting room does not have to cross the bed. It can be bolted from inside."),
    ]
    y = H - 136
    for title, body in bullets:
        c.setFillColor(NEW)
        c.circle(tx + 4, y + 2, 2.3, fill=1, stroke=0)
        c.setFillColor(INK)
        c.setFont("Times-Bold", 9)
        c.drawString(tx + 14, y, title)
        y -= 13
        c.setFillColor(GREY)
        c.setFont("Times-Roman", 8)
        words = body.split()
        line = ""
        for w in words:
            trial = (line + " " + w).strip()
            if c.stringWidth(trial, "Times-Roman", 8) > 300:
                c.drawString(tx + 14, y, line)
                y -= 11
                line = w
            else:
                line = trial
        if line:
            c.drawString(tx + 14, y, line)
            y -= 16

    # walk-through
    y -= 8
    c.setFillColor(INK)
    c.setFont("Times-Bold", 12)
    c.drawString(tx, y, "How you move")
    y -= 8
    c.setStrokeColor(INK)
    c.setLineWidth(0.8)
    c.line(tx, y, tx + 180, y)
    y -= 18
    steps = [
        "Come up the stair. The landing is at the east end.",
        "The store door is directly in front of that landing.",
        "Turn west, then north, into the sitting room. Or step east into the passage.",
        "From the sitting room, the new door opens straight into the bedroom.",
        "From the bedroom, the new door opens straight into the bathroom.",
        "The passage door is the other way into the same bathroom.",
        "North balcony is still through the 4-panel sliding door.",
        "Front balcony is through the passage, south door.",
    ]
    c.setFont("Times-Roman", 8.5)
    for i, stext in enumerate(steps, 1):
        c.setFillColor(BLUE)
        c.setFont("Times-Bold", 8.5)
        c.drawString(tx, y, f"{i}")
        c.setFillColor(INK)
        c.setFont("Times-Roman", 8.5)
        c.drawString(tx + 16, y, stext)
        y -= 16

    y -= 10
    c.setFillColor(INK)
    c.setFont("Times-Bold", 12)
    c.drawString(36, 168, "Keep  /  change")
    c.setFont("Times-Roman", 8.5)
    c.setFillColor(GREY)
    keep = "KEEP    External walls, stair, both balconies, sitting windows, bedroom east window, bathroom ventilator, wall-hung W.C., raised wet floor, shower taps."
    chg = "CHANGE    New sitting-to-bedroom door. New bedroom-to-bathroom door. Store moved to the stair landing. Basin moved inside, onto the north wall. Old passage basin deleted. Bedroom grows into the old store."
    def wrap(text, x, y, width, font="Times-Roman", size=8.5, color=GREY):
        c.setFont(font, size)
        c.setFillColor(color)
        words = text.split()
        line = ""
        for w in words:
            trial = (line + " " + w).strip()
            if c.stringWidth(trial, font, size) > width:
                c.drawString(x, y, line)
                y -= 12
                line = w
            else:
                line = trial
        if line:
            c.drawString(x, y, line)
            y -= 12
        return y
    y = 150
    y = wrap(keep, 36, y, 1100)
    y -= 4
    y = wrap(chg, 36, y, 1100, color=NEW)

    c.setFillColor(INK)
    c.setFont("Times-Italic", 8)
    c.drawString(36, 36, "Sheet 02 of 02    ·    Dr. Yedhenai Patel    ·    First floor revised design    ·    Check every opening on site before the lintel is cast")
    c.setFont("Times-Roman", 8)
    c.drawRightString(W - 36, 36, "Dimensions in feet and inches")


def main():
    c = canvas.Canvas(OUT, pagesize=PAGE)
    c.setTitle("Revised first floor — attached bathroom, direct bedroom, store at stair")
    c.setAuthor("Revised from the architect reference pack")
    draw_floor(c)
    c.showPage()
    draw_bath_sheet(c)
    c.save()
    print(OUT)


if __name__ == "__main__":
    main()
