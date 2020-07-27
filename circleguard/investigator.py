import math

import numpy as np

from circleguard.enums import Key, Detect
from circleguard.result import RelaxResult, CorrectionResult, TimewarpResult
from circleguard.mod import Mod
from slider.beatmap import Circle, Slider, Spinner

class Investigator:
    """
    Manages the investigation of individual
    :class:`~.replay.Replay`\s for cheats.

    Parameters
    ----------
    replay: :class:`~.replay.Replay`
        The replay to investigate.
    detect: :class:`~.Detect`
        What cheats to investigate the replay for.
    beatmap: :class:`slider.beatmap.Beatmap`
        The beatmap to calculate ur from, with the replay. Should be ``None``
        if ``Detect.RELAX in detect`` is ``False``.

    See Also
    --------
    :class:`~.comparer.Comparer`, for comparing multiple replays.
    """

    MASK = int(Key.M1) | int(Key.M2)
    # https://osu.ppy.sh/home/changelog/stable40/20190207.2
    VERSION_SLIDERBUG_FIXED_STABLE = 20190207
    # https://osu.ppy.sh/home/changelog/cuttingedge/20190111
    VERSION_SLIDERBUG_FIXED_CUTTING_EDGE = 20190111

    def __init__(self, replay, detect, max_angle, min_distance, beatmap=None):
        self.replay = replay
        self.detect = detect
        self.max_angle = max_angle
        self.min_distance = min_distance
        self.beatmap = beatmap
        self.detect = detect

    def investigate(self):
        replay = self.replay
        # equivalent of filtering out replays with no replay data from comparer on init
        if replay.replay_data is None:
            return
        if self.detect & Detect.RELAX:
            ur = self.ur(replay, self.beatmap)
            yield RelaxResult(replay, ur)
        if self.detect & Detect.CORRECTION:
            snaps = self.aim_correction(replay, self.max_angle, self.min_distance)
            yield CorrectionResult(replay, snaps)
        if self.detect & Detect.TIMEWARP:
            frametimes = self.frametimes(replay)
            frametime = self.median_frametime(frametimes)
            yield TimewarpResult(replay, frametime, frametimes)

    @staticmethod
    def ur(replay, beatmap):
        """
        Calculates the ur of ``replay`` when played against ``beatmap``.

        Parameters
        ----------
        replay: :class:`~.Replay`
            The replay to calculate the ur of.
        beatmap: :class:`slider.beatmap.Beatmap`
            The beatmap to calculate ``replay``'s ur with.
        """

        easy = Mod.EZ in replay.mods
        hard_rock = Mod.HR in replay.mods
        hitobjs = beatmap.hit_objects(easy=easy, hard_rock=hard_rock)

        version = replay.game_version


        if version is None:
            # estimate version with timestamp, this is only accurate if the user
            #  keeps their game up to date. We don't get the timestamp from
            # `ReplayMap`, only `ReplayPath`
            version = int(f"{replay.timestamp.year}{replay.timestamp.month:02d}"
                          f"{replay.timestamp.day:02d}")
            concrete_version = False
        else:
            concrete_version = True

        OD = beatmap.od(easy=easy, hard_rock=hard_rock)
        CS = beatmap.cs(easy=easy, hard_rock=hard_rock)
        keydown_frames = Investigator.keydown_frames(replay)
        hits = Investigator.hits(hitobjs, keydown_frames, OD, CS, version, concrete_version)
        diff_array = []

        for hitobj_time, press_time in hits:
            diff_array.append(press_time - hitobj_time)
        return np.std(diff_array) * 10

    @staticmethod
    def aim_correction(replay, max_angle, min_distance):
        """
        Calculates the angle between each set of three points (a,b,c) and finds
        points where this angle is extremely acute and neither ``|ab|`` or
        ``|bc|`` are small.

        Parameters
        ----------
        replay: :class:`~.Replay`
            The replay to investigate for aim correction.
        max_angle: float
            Consider only (a,b,c) where ``∠abc < max_angle``
        min_distance: float
            Consider only (a,b,c) where ``|ab| > min_distance`` and
            ``|ab| > min_distance``.

        Returns
        -------
        list[:class:`~.Snap`]
            Hits where the angle was less than ``max_angle`` and the distance
            was more than ``min_distance``.

        Notes
        -----
        This does not detect correction where multiple datapoints are placed
        at the correction site (which creates a small ``min_distance``).

        Another possible method is to look at the ratio between the angle
        and distance.

        See Also
        --------
        :meth:`~.aim_correction_sam` for an alternative, unused approach
        involving velocity and jerk.
        """
        # when we leave mutliple frames with the same time values, they
        # sometimes get detected (falesly) as aim correction.
        # TODO Worth looking into a bit more to see if we can avoid it without
        # removing the frames entirely.
        t, xy = Investigator.remove_unique(replay.t, replay.xy)
        t = t[1:-1]

        # labelling three consecutive points a, b and c
        ab = xy[1:-1] - xy[:-2]
        bc = xy[2:] - xy[1:-1]
        ac = xy[2:] - xy[:-2]
        # Distance a to b, b to c, and a to c
        AB = np.linalg.norm(ab, axis=1)
        BC = np.linalg.norm(bc, axis=1)
        AC = np.linalg.norm(ac, axis=1)
        # Law of cosines, solve for beta
        # AC^2 = AB^2 + BC^2 - 2 * AB * BC * cos(beta)
        # cos(beta) = -(AC^2 - AB^2 - BC^2) / (2 * AB * BC)
        num = -(AC ** 2 - AB ** 2 - BC ** 2)
        denom = (2 * AB * BC)
        # use true_divide for handling division by zero
        cos_beta = np.true_divide(num, denom, out=np.full_like(num, np.nan), where=denom!=0)
        # rounding issues makes cos_beta go out of arccos' domain, so restrict it
        cos_beta = np.clip(cos_beta, -1, 1)

        beta = np.rad2deg(np.arccos(cos_beta))

        min_AB_BC = np.minimum(AB, BC)
        dist_mask = min_AB_BC > min_distance
        # use less to avoid comparing to nan
        angle_mask = np.less(beta, max_angle, where=~np.isnan(beta))
        # boolean array of datapoints where both distance and angle requirements are met
        mask = dist_mask & angle_mask

        return [Snap(t, b, d) for (t, b, d) in zip(t[mask], beta[mask], min_AB_BC[mask])]

    @staticmethod
    def aim_correction_sam(replay_data, num_jerks, min_jerk):
        """
        Calculates the jerk at each moment in the Replay, counts the number of times
        it exceeds min_jerk and reports a positive if that number is over num_jerks.
        Also reports all suspicious jerks and their timestamps.

        WARNING
        -------
        Unused function. Kept for historical purposes and ease of viewing in
        case we want to switch to this track of aim correction in the future,
        or provide it as an alternative.
        """

        # get all replay data as an array of type [(t, x, y, k)]
        txyk = np.array(replay_data)

        # drop keypresses
        txy = txyk[:, :3]

        # separate time and space
        t = txy[:, 0]
        xy = txy[:, 1:]

        # j_x = (d/dt)^3 x
        # calculated as (d/dT dT/dt)^3 x = (dT/dt)^3 (d/dT)^3 x
        # (d/dT)^3 x = d(d(dx/dT)/dT)/dT
        # (dT/dt)^3 = 1/(dt/dT)^3
        dtdT = np.diff(t)
        d3xy = np.diff(xy, axis=0, n=3)
        # safely calculate the division and replace with zero if the divisor is zero
        # dtdT is sliced with 2: because differentiating drops one element for each order (slice (n - 1,) to (n - 3,))
        # d3xy is of shape (n - 3, 2) so dtdT is also reshaped from (n - 3,) to (n - 3, 1) to align the axes.
        jerk = np.divide(d3xy, dtdT[2:, None] ** 3, out=np.zeros_like(d3xy), where=dtdT[2:,None]!=0)

        # take the absolute value of the jerk
        jerk = np.linalg.norm(jerk, axis=1)

        # create a mask of where the jerk reaches suspicious values
        anomalous = jerk > min_jerk
        # and retrieve and store the timestamps and the values themself
        timestamps = t[3:][anomalous]
        values = jerk[anomalous]
        # reshape to an array of type [(t, j)]
        jerks = np.vstack((timestamps, values)).T

        # count the anomalies
        ischeat = anomalous.sum() > num_jerks

        return [jerks, ischeat]

    @staticmethod
    def frametimes(replay):
        """
        Returns the time between each pair of consecutive frames in ``replay``.

        Parameters
        ----------
        replay: :class:`~.Replay`
            The replay to get the frametimes of.
        """
        # replay.t is cumsum so convert it back to "time since previous frame"
        return np.diff(replay.t)

    @staticmethod
    def median_frametime(frametimes):
        """
        Calculates the median time between the frames in ``frametimes``.

        Parameters
        ----------
        frametimes: list[int]
            The frametimes to find the median of.

        Notes
        -----
        Median is used instead of mean to lessen the effect of outliers.
        """
        return np.median(frametimes)

    @staticmethod
    def keydown_frames(replay):
        """
        Get the frames of ``replay`` which had a keydown event, and we should
        consider eligible to hit a hitobject.

        Parameters
        ----------
        replay: :class:`~.Replay`
            The replay to get the keydown frames of.

        Returns
        -------
        ndarray(float, [float, float], float)
            The keydown frames for the replay. The first float is the time of
            that frame, the second and third floats are the x and y position
            of the cursor at that frame, and the fourth float is the time of
            the previous frame.
        """
        keydown_frames = []
        # the keys currently down for each frame
        keypresses = replay.k & Investigator.MASK

        # the keydowns for each frame. Frames are "keydown" frames if an
        # additional key was pressed from the previous frame. If keys pressed
        # remained the same or decreased (a key previously pressed is no longer
        # pressed) from the previous frame, ``keydowns`` is zero for that frame.
        keydowns = keypresses & ~np.insert(keypresses[:-1], 0, 0)

        for i, keydown in enumerate(keydowns):
            if keydown != 0:
                # keep track of the previous frame as those affect the duration of notelock
                keydown_frames.append([replay.t[i], replay.xy[i], replay.t[i-1]])

        # add a duplicate frame when 2 keys are pressed at the same time
        keydowns = keydowns[keydowns != 0]
        i = 0
        for j in np.where(keydowns == Investigator.MASK)[0]:
            keydown_frames.insert(j + i + 1, keydown_frames[j + i])
            i += 1

        return keydown_frames

    # TODO add exception for 2b objects (>1 object at the same time) for current
    #  version of notelock
    @staticmethod
    def hits(hitobjs, keydowns, OD, CS, version, concrete_version):
        """
        Determines the hits (where any hitobject was hit for the first time)
        when playing the ``keydowns`` against the ``hitobjs``.

        Parameters
        ----------
        hitobjs: list[:class:`slider.beatmap.HitObject`]
            The hitobjects to play ``keydowns`` against.
        keydowns: ndarray(float, [float, float], bool)
            The keydown frames to play against ``hitobjs``. The first float is
            the time of that frame, the second and third floats are the x and y
            position of the cursor at that frame, and the bool is whether this
            frame was a zero frametime frame.
        OD: float
            The Overall Difficulty of the beatmap ``hitobjs`` comes from.
        CS: float
            The Circle Size of the beatmap ``hitobjs`` comes from.
        version: int
            The version the replay ``keydowns`` comes from was played on.
        concrete_version: bool
            Whether we know for certain ``version`` is accurate. In cases where
            we don't know the version of the game, we can estimate it by using
            the time the replay was played, and ``concrete_version`` should be
            ``False``. Otherwise, if we know the exact version, it should be
            ``True``.
        """
        if concrete_version:
            version_sliderbug_fixed = Investigator.VERSION_SLIDERBUG_FIXED_CUTTING_EDGE
        else:
            # if we're only estimating the version, assume the replay was played
            # on stable. if we used the cutting edge version instead, we would
            # be incorrectly using logic for sliderbug being fixed for all
            # replays between the cutting edge version and the stable version
            # which were played on stable.
            # This is wrong for cutting edge replays between those two versions
            # which do not have a concrete version, but that's better than being
            # wrong for stable replays between those two versions.
            version_sliderbug_fixed = Investigator.VERSION_SLIDERBUG_FIXED_STABLE


        hits = []

        # stable converts OD (and CS), which are originally a float32, to a
        # double and this causes some hitwindows to be messed up when casted to
        # an int so we replicate this
        hitwindow = int(150 + 50 * (5 - float(np.float32(OD))) / 5)

        # attempting to match stable hitradius
        hitradius = np.float32(64 * ((1.0 - np.float32(0.7) * (float(np.float32(CS)) - 5) / 5)) / 2) * np.float32(1.00041)

        hitobj_i = 0
        keydown_i = 0

        while hitobj_i < len(hitobjs) and keydown_i < len(keydowns):
            hitobj = hitobjs[hitobj_i]
            hitobj_t = hitobj.time.total_seconds() * 1000
            hitobj_xy = [hitobj.position.x, hitobj.position.y]

            keydown_t = keydowns[keydown_i][0]
            keydown_xy = keydowns[keydown_i][1]
            prev_t = keydowns[keydown_i][2]

            if isinstance(hitobj, Circle):
                hitobj_type = 0
                # from testing, circle end time is 1ms longer than its hitwindow
                hitobj_end_time = hitobj_t + hitwindow + 1
            elif isinstance(hitobj, Slider):
                hitobj_type = 1
                hitobj_end_time = hitobj.end_time.total_seconds() * 1000
            else:
                hitobj_type = 2
                hitobj_end_time = hitobj.end_time.total_seconds() * 1000

            # before sliderbug fix, notelock ended after hitwindow50
            if version < version_sliderbug_fixed:
                notelock_end_time = hitobj_t + hitwindow
                # exception for sliders/spinners, where notelock ends after
                # hitobject end time if it's earlier
                if hitobj_type != 0:
                    notelock_end_time = min(notelock_end_time, hitobj_end_time)
            # after sliderbug fix, notelock ends after hitobject end time
            else:
                # explanation of how notelock works currently:
                # the next hitobject can not be pressed on until the current object is "removed"
                # (when player interaction with the hitobject is no longer possible)
                # there are 3 ways a hitobject can be removed.
                # 1. missing from pressing too early
                # 2. pressing on the hitobject within the hitwindow50 ranges (a hit)
                # 3. auto missing from not pressing on the hitobject at all
                # (the game auto misses hitobjects after hitobject_end_time)
                # the one that causes notelock is the 3rd one.
                # but it isn't as simple as using the hitobject_end_time as the notelock_end_time
                # since the game checks keypresses first before updating hitobjects
                # best way to explain this is with an example
                # e.g. there are two circles, one at 1000ms and one at 1050ms, the hitwindow50 is 100ms
                # the replay data has a keydown at 1105ms with xy position on the 2nd circle
                # and the frame in the replay data before that is at 1095ms
                # even though the keydown time (1105ms) is after the first circle's time + hitwindow50 (1100ms)
                # the game will show notelock on the 2nd circle
                # this is because at the frame 1105ms, the game first checks the keydown
                # with the hitobjects that can be interacted with
                # this includes the first circle as the game has not removed it yet
                # (the last check was at 1095ms, where the first circle still exists)
                # after checking the keydown, the game then removes the first circle
                # however if that 1095ms frame was at 1104ms instead, the 2nd circle will be hit
                # as the 1104ms frame has caused the game to remove the first circle
                # thus allowing the 2nd circle to be clicked on by the keydown at 1105ms
                if keydown_t >= hitobj_end_time and prev_t < hitobj_end_time:
                    notelock_end_time = prev_t + 1000/60
                else:
                    notelock_end_time = hitobj_end_time


            # can't press on hitobjects before hitwindowmiss
            if keydown_t <= hitobj_t - 400:
                keydown_i += 1
                continue

            if keydown_t <= hitobj_t - hitwindow:
                # pressing on a circle or slider during hitwindowmiss will cause
                #  a miss
                if np.linalg.norm(keydown_xy - hitobj_xy) <= hitradius and hitobj_type != 2:

                    # sliders don't disappear after missing
                    # so we skip to the press_i that is after notelock_end_time
                    if hitobj_type == 1 and version >= version_sliderbug_fixed:
                        while keydowns[keydown_i][0] < notelock_end_time:
                            keydown_i += 1
                            if keydown_i >= len(keydowns):
                                break
                            # notelock_end_time changes for a keypress depending on the previous frame
                            # so it needs to be updated every time keydown_i is increased
                            prev_t = keydowns[keydown_i][2]
                            if keydown_t >= hitobj_end_time and prev_t < hitobj_end_time:
                                notelock_end_time = prev_t + 1000/60
                            else:
                                notelock_end_time = hitobj_end_time
                    else:
                        keydown_i += 1
                    hitobj_i += 1
                # keypress not on object, so we move to the next keypress
                else:
                    keydown_i += 1
            elif keydown_t >= notelock_end_time:
                # can no longer interact with hitobject after notelock_end_time
                # so we move to the next object
                hitobj_i += 1
            else:
                if keydown_t < hitobj_t + hitwindow and np.linalg.norm(keydown_xy - hitobj_xy) <= hitradius and hitobj_type != 2:
                    hits.append([hitobj_t, keydown_t])

                    # sliders don't disappear after clicking
                    # so we skip to the press_i that is after notelock_end_time
                    if hitobj_type == 1 and version >= version_sliderbug_fixed:
                        while keydowns[keydown_i][0] < notelock_end_time:
                            keydown_i += 1
                            if keydown_i >= len(keydowns):
                                break
                            # notelock_end_time changes for a keypress depending on the previous frame
                            # so it needs to be updated every time keydown_i is increased
                            prev_t = keydowns[keydown_i][2]
                            if keydown_t >= hitobj_end_time and prev_t < hitobj_end_time:
                                notelock_end_time = prev_t + 1000/60
                            else:
                                notelock_end_time = hitobj_end_time
                    else:
                        keydown_i += 1
                    hitobj_i += 1
                # keypress not on object, so we move to the next keypress
                else:
                    keydown_i += 1

        return hits

    # TODO (some) code duplication with this method and a similar one in
    # ``Comparer``. Refactor Investigator and Comparer to inherit from a base
    # class, or move this method to utils. Preferrably the former.
    @staticmethod
    def remove_unique(t, k):
        t, t_sort = np.unique(t, return_index=True)
        k = k[t_sort]
        return (t, k)

class Snap():
    """
    A suspicious hit in a replay, specifically so because it snaps away from
    the otherwise normal path. Snaps currently represent the middle datapoint
    in a set of three replay datapoints.

    Parameters
    ----------
    time: int
        The time value of the middle datapoint, in ms. 0 represents the
        beginning of the replay.
    angle: float
        The angle between the three datapoints.
    distance: float
        ``min(dist_a_b, dist_b_c)`` if ``a``, ``b``, and ``c`` are three
        datapoints with ``b`` being the middle one.

    See Also
    --------
    :meth:`~.Investigator.aim_correction`
    """
    def __init__(self, time, angle, distance):
        self.time = time
        self.angle = angle
        self.distance = distance

    def __eq__(self, other):
        return (self.time == other.time and self.angle == other.angle
                and self.distance == other.distance)
