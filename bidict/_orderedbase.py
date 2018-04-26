# -*- coding: utf-8 -*-
# Copyright 2018 Joshua Bronson. All Rights Reserved.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.


#==============================================================================
#                    * Welcome to the bidict source code *
#==============================================================================

# Doing a code review? You'll find a "Code review nav" comment like the one
# below at the top and bottom of the most important source files. This provides
# a suggested initial path through the source when reviewing.
#
# Note: If you aren't reading this on https://github.com/jab/bidict, you may be
# viewing an outdated version of the code. Please head to GitHub to review the
# latest version, which contains important improvements over older versions.
#
# Thank you for reading and for any feedback you provide.

#                             * Code review nav *
#==============================================================================
#  ← Prev: _bidict.py       Current: _orderedbase.py  Next: _frozenordered.py →
#==============================================================================


"""Provides :class:`OrderedBidictBase`."""

from weakref import ref

from ._base import _WriteResult, BidictBase
from ._miss import _MISS
from .compat import KeysView, ItemsView, Mapping, PY2, iteritems, izip


class _Node(object):  # pylint: disable=too-few-public-methods
    """A node in a circular doubly-linked list
    that stores the items in an ordered bidict.

    Only weak references to the next and previous nodes
    are held to avoid creating strong reference cycles.
    """

    __slots__ = ('item', '_prv', '_nxt', '__weakref__')

    def __init__(self, item, prv, nxt):
        self.item = item
        self._setprv(prv)
        self._setnxt(nxt)

    def __repr__(self):  # pragma: no cover - just useful for debugging
        return '%s(%s, prv=%s, nxt=%s)' % (
            self.__class__.__name__, self.item,
            self.prv and self.prv.item,
            self.nxt and self.nxt.item)

    def _getprv(self):
        return self._prv() if isinstance(self._prv, ref) else self._prv

    def _setprv(self, prv):
        self._prv = prv and ref(prv)

    prv = property(_getprv, _setprv)

    def _getnxt(self):
        return self._nxt() if isinstance(self._nxt, ref) else self._nxt

    def _setnxt(self, nxt):
        self._nxt = nxt and ref(nxt)

    nxt = property(_getnxt, _setnxt)

    def __getstate__(self):
        """Convert weakrefs to strong refs so that instances can be pickled.

        *See also* :meth:`object.__getstate__`
        """
        item = self.item
        _nxt = self._nxt
        _prv = self._prv
        return {'item': item, '_prv': _prv and _prv(), '_nxt': _nxt and _nxt()}

    def __setstate__(self, state):
        """Convert strong refs that were converted from weak during pickling
        back to weakrefs upon unpickling to avoid creating reference cycles.
        """
        # pylint: disable=attribute-defined-outside-init
        self.item = state['item']
        self._prv = state['_prv'] and ref(state['_prv'])
        self._nxt = state['_nxt'] and ref(state['_nxt'])


def _make_sentinel():
    """Create a special node that initially represents a new empty circular linked list,
    i.e. its next and previous references point back to itself.
    """
    sntl = _Node(None, None, None)
    sntl.nxt = sntl.prv = sntl
    return sntl


def _iter_nodes(sntl, reverse=False):
    """Given a sentinel node of a linked list,
    iterate over the remaining nodes in the order specified by *reverse*.
    """
    attr = 'prv' if reverse else 'nxt'
    node = getattr(sntl, attr)
    while node is not sntl:  # lgtm [py/comparison-using-is]
        yield node
        node = getattr(node, attr)


class OrderedBidictBase(BidictBase):  # lgtm [py/missing-equals]
    """Base class implementing an ordered :class:`BidirectionalMapping`."""

    __slots__ = ('_sntl',)

    def __init__(self, *args, **kw):
        """Make a new ordered bidirectional mapping.
        The signature is the same as that of regular dictionaries.
        Items passed in are added in the order they are passed,
        respecting this bidict type's duplication policies along the way.
        The order in which items are inserted is remembered,
        similar to :class:`collections.OrderedDict`.
        """
        self._sntl = _make_sentinel()

        # Like unordered bidicts, ordered bidicts also store
        # two backing one-directional mappings `fwdm` and `invm`.
        # But rather than mapping key to val and val to key (respectively),
        # they map key to node and val to node (respectively),
        # where `node` is the same when key and val are associated with one another.
        # To effect this difference, _write_item and _undo_write are overridden.
        # But much of the rest of BidictBase's implementation,
        # including BidictBase.__init__ and BidictBase._update,
        # are inherited and able to be reused without modification.
        super(OrderedBidictBase, self).__init__(*args, **kw)

    def _init_inv(self):
        super(OrderedBidictBase, self)._init_inv()
        self.inv._sntl = self._sntl  # pylint: disable=protected-access

    # Can't reuse BidictBase.copy since ordered bidicts have different internal structure.
    def copy(self):
        """A shallow copy of this ordered bidict."""
        # Fast copy implementation bypassing __init__. See comments in :meth:`BidictBase.copy`.
        copy = self.__class__.__new__(self.__class__)
        sntl = _make_sentinel()
        fwdm = dict.fromkeys(self._fwdm)
        invm = dict.fromkeys(self._invm)
        cur = sntl
        nxt = sntl.nxt
        for item in iteritems(self):
            nxt = _Node(item, cur, sntl)
            key, val = item
            cur.nxt = fwdm[key] = invm[val] = nxt
            cur = nxt
        sntl.prv = nxt
        copy._sntl = sntl  # pylint: disable=protected-access
        copy._fwdm = fwdm  # pylint: disable=protected-access
        copy._invm = invm  # pylint: disable=protected-access
        copy._init_inv()  # pylint: disable=protected-access
        return copy

    def __getitem__(self, key):
        nodefwd = self._fwdm[key]
        val = nodefwd.item[not self._isinv]
        nodeinv = self._invm[val]
        assert nodeinv is nodefwd
        return val

    def _pop(self, key):
        nodefwd = self._fwdm.pop(key)
        val = nodefwd.item[not self._isinv]
        nodeinv = self._invm.pop(val)
        assert nodeinv is nodefwd
        nodefwd.prv.nxt = nodefwd.nxt
        nodefwd.nxt.prv = nodefwd.prv
        return val

    def _isdupitem(self, key, val, dedup_result):
        """Return whether (key, val) duplicates an existing item."""
        isdupkey, isdupval, nodeinv, nodefwd = dedup_result
        isdupitem = nodeinv is nodefwd
        if isdupitem:
            assert isdupkey
            assert isdupval
            assert nodefwd.item == ((val, key) if self._isinv else (key, val))
        return isdupitem

    def _write_item(self, key, val, dedup_result):  # pylint: disable=too-many-locals
        fwdm = self._fwdm
        invm = self._invm
        isinv = self._isinv
        nodeitem = (val, key) if isinv else (key, val)
        isdupkey, isdupval, nodeinv, nodefwd = dedup_result
        if not isdupkey and not isdupval:
            sntl = self._sntl
            last = sntl.prv
            node = _Node((key, val), last, sntl)
            last.nxt = sntl.prv = fwdm[key] = invm[val] = node
            oldkey = oldval = _MISS
        elif isdupkey and isdupval:
            oldval = (nodeinv if isinv else nodefwd).item[1]
            oldkey = (nodefwd if isinv else nodeinv).item[0]
            assert oldkey != key
            assert oldval != val
            # We have to collapse nodefwd and nodeinv into a single node, i.e. drop one of them.
            # Drop nodeinv, so that the item with the same key is the one overwritten in place.
            nodeinv.prv.nxt = nodeinv.nxt
            nodeinv.nxt.prv = nodeinv.prv
            # Don't remove nodeinv's references to its neighbors since
            # if the update fails, we'll need them to undo this write.
            # Python's garbage collector should still be able to detect when
            # nodeinv is garbage and reclaim the memory.
            # Update fwdm and invm.
            tmp = fwdm.pop(oldkey)
            assert tmp is nodeinv
            tmp = invm.pop(oldval)
            assert tmp is nodefwd
            fwdm[key] = invm[val] = nodefwd
            # Update nodefwd with new item.
            nodefwd.item = nodeitem
        elif isdupkey:
            oldval = (nodeinv if isinv else nodefwd).item[1]
            oldkey = _MISS
            oldnodeinv = invm.pop(oldval)
            assert oldnodeinv is nodefwd
            invm[val] = nodefwd
            node = nodefwd
        else:  # isdupval
            oldkey = (nodefwd if isinv else nodeinv).item[0]
            oldval = _MISS
            oldnodefwd = fwdm.pop(oldkey)
            assert oldnodefwd is nodeinv
            fwdm[key] = nodeinv
            node = nodeinv
        if isdupkey ^ isdupval:
            node.item = nodeitem
        return _WriteResult(key, val, oldkey, oldval)

    def _undo_write(self, dedup_result, write_result):  # pylint: disable=too-many-locals
        fwdm = self._fwdm
        invm = self._invm
        isdupkey, isdupval, nodeinv, nodefwd = dedup_result
        key, val, oldkey, oldval = write_result
        if not isdupkey and not isdupval:
            self._pop(key)
        elif isdupkey and isdupval:
            # nodeinv.item was never changed, so it should still have its original item.
            assert nodeinv.item == (oldkey, val)
            # Restore original items.
            nodefwd.item = (key, oldval)
            nodeinv.prv.nxt = nodeinv.nxt.prv = nodeinv
            fwdm[oldkey] = invm[val] = nodeinv
            invm[oldval] = fwdm[key] = nodefwd
        elif isdupkey:
            nodefwd.item = (key, oldval)
            tmp = invm.pop(val)
            assert tmp is nodefwd
            invm[oldval] = nodefwd
            assert fwdm[key] is nodefwd
        else:  # isdupval
            nodeinv.item = (oldkey, val)
            tmp = fwdm.pop(key)
            assert tmp is nodeinv
            fwdm[oldkey] = nodeinv
            assert invm[val] is nodeinv

    def __iter__(self, reverse=False):
        """An iterator over this bidict's items in order."""
        idx = self._isinv
        for node in _iter_nodes(self._sntl, reverse=reverse):
            yield node.item[idx]

    def __reversed__(self):
        """An iterator over this bidict's items in reverse order."""
        for key in self.__iter__(reverse=True):
            yield key

    def equals_order_sensitive(self, other):
        """Order-sensitive equality check.

        *See also* :ref:`eq-order-insensitive`
        """
        if not isinstance(other, Mapping) or len(self) != len(other):
            return False
        return all(i == j for (i, j) in izip(iteritems(self), iteritems(other)))

    def __repr_delegate__(self):
        """See :meth:`bidict.BidictBase.__repr_delegate__`."""
        return list(iteritems(self))

    # Override the `values` implementation inherited from `Mapping`. Implemented in terms of
    # self.inv.keys(), so that on Python 3 we end up returning a KeysView (dict_keys) object.
    def values(self):
        """A set-like object providing a view on the contained values.

        Note that because the values of a :class:`~bidict.BidirectionalMapping`
        are the keys of its inverse,
        this returns a :class:`~collections.abc.KeysView`
        rather than a :class:`~collections.abc.ValuesView`,
        which has the advantages of constant-time containment checks
        and supporting set operations.
        """
        return self.inv.keys()

    if PY2:
        def viewvalues(self):  # noqa: D102; pylint: disable=missing-docstring
            return KeysView(self.inv)

        viewvalues.__doc__ = values.__doc__
        values.__doc__ = 'A list of the contained values.'

        def viewitems(self):
            """A set-like object providing a view on the contained items."""
            return ItemsView(self)

        def viewkeys(self):
            """A set-like object providing a view on the contained keys."""
            return KeysView(self)


#                             * Code review nav *
#==============================================================================
#  ← Prev: _bidict.py       Current: _orderedbase.py  Next: _frozenordered.py →
#==============================================================================