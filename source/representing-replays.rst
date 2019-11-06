Representing Replays
====================

Circlecore needs a replay to investigate before it can tell you anything
about if that replay is cheated. There are several ways to create a replay
through circlecore.

All four of the following classes are subclasses of |Loadable|.

.. note::

    All of the following objects are lazy-loaded. That is, they are as cheap
    as possible to instantiate, and only incur a loading penalty when
    necessary (see |cg.load|, |cg.load_info|, and |cg.run|).


Replay
------

A |Replay| is the most basic object of circlecore. One replay object represents
one play made by a user. We define two |Replay| subclasses.

ReplayMap
~~~~~~~~~

|ReplayMap| represents a replay by a user on a map. For instance,

.. code-block:: python

    r1 = ReplayMap(221777, 2757689)

represents the highest scoring replay by user ``2757689`` on map ``221777``. To
restrict this to a certain replay, specify a mods argument. This represents
specifically the ``HDHR`` play by the same user on the same map.

.. code-block:: python

    r1 = ReplayMap(221777, 2757689, mods=Mod.HD + Mod.DT)

While in this case these are identical replays, there are times a user has two
available replays on a map, with different mods. Because of how osu! stores
replays, it is impossible to have two available replays with the same
mod combination.

ReplayPath
~~~~~~~~~~

|ReplayPath| represents a replay stored locally in an ``osr`` file. For
instance,

.. code-block:: python

    r2 = ReplayPath("/Users/tybug/Desktop/replays/replay1.osr")

represents the replay in the file ``/Users/tybug/Desktop/replays/replay1.osr``.

Replay Containers
-----------------

True to its name, a |ReplayContainer| represents a set of replays. These are
provided as a convenience to minimize the amount of information you need to
know to construct a view of map or player.


Map
~~~

It is common to want to investigate all, or a subset of, a map's leaderboard.

.. code-block:: python

    # top 50 scores on the map
    m = Map(221777, num=50)
    # top 12 scores with exactly HD (not HDDT or another variation). Due to
    # api restrictions, we do not provide fuzzy matching.
    m = Map(221777, num=12, mods=Mod.HD)
    # 1st, 4th, 5th, 6th, 7h, 8th, 10th, 11th, and 12th top scores
    m = Map(221777, span="1, 4-8, 10-12")
    # 1st and 49th scores with exactly HD
    m = Map(221777, span="1, 49", mods=Mod.HD)


Users
~~~~~

Similar to |Map|, a |User| represents the top plays of a user.

.. code-block:: python

    # top 50 scores of the user
    u = User(2757689, num=50)
    # top 12 scores with exactly HD (not HDDT or another variation). Due to
    # api restrictions, we do not provide fuzzy matching.
    u = User(2757689, num=12, mods=Mod.HD)
    # 1st, 4th, 5th, 6th, 7h, 8th, 10th, 11th, and 12th top scores
    u = User(2757689, span="1, 4-8, 10-12")
    # 1st and 49th scores with exactly HD
    u = User(2757689, span="1, 49", mods=Mod.HD)