"""AVL tree: a BST that rebalances itself with rotations after every insert.

Search / iter_from / height are inherited unchanged from BST. Only insert
differs, so any speed difference you measure comes purely from balancing.
Height is guaranteed <= ~1.44 * log2(n), so recursion depth stays tiny.
"""

from bst import BST, Node


def _h(node):
    return node.height if node else 0


def _update(node):
    node.height = 1 + max(_h(node.left), _h(node.right))


class AVLTree(BST):
    name = "AVL"

    def __init__(self):
        super().__init__()
        self.rotations = 0

    def _rotate_right(self, y):
        x = y.left
        y.left = x.right
        x.right = y
        _update(y)
        _update(x)
        self.rotations += 1
        return x

    def _rotate_left(self, x):
        y = x.right
        x.right = y.left
        y.left = x
        _update(x)
        _update(y)
        self.rotations += 1
        return y

    def _rebalance(self, node):
        _update(node)
        balance = _h(node.left) - _h(node.right)
        if balance > 1:                                   # left heavy
            if _h(node.left.left) < _h(node.left.right):  # left-right case
                node.left = self._rotate_left(node.left)
            return self._rotate_right(node)
        if balance < -1:                                  # right heavy
            if _h(node.right.right) < _h(node.right.left):  # right-left case
                node.right = self._rotate_right(node.right)
            return self._rotate_left(node)
        return node

    def _insert(self, node, key, value):
        if node is None:
            self.size += 1
            return Node(key, value)
        self.comparisons += 1
        if key == node.key:
            node.values.append(value)
            return node
        if key < node.key:
            node.left = self._insert(node.left, key, value)
        else:
            node.right = self._insert(node.right, key, value)
        return self._rebalance(node)

    def insert(self, key, value):
        self.root = self._insert(self.root, key, value)

    def height(self):
        return _h(self.root)