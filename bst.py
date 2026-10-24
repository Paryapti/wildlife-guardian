"""Plain (unbalanced) binary search tree.

Everything is iterative on purpose: if the data arrives sorted, a plain BST
degenerates into a linked list with height ~N, and a recursive version would
crash with RecursionError. Iteration keeps it working (just slowly), which is
exactly the behaviour the AVL tree is meant to fix.

Equal keys share one node: node.values is a list of every record with that key.
"""


class Node:
    __slots__ = ("key", "values", "left", "right", "height")

    def __init__(self, key, value):
        self.key = key
        self.values = [value]
        self.left = None
        self.right = None
        self.height = 1  # only maintained by the AVL tree


class BST:
    name = "BST"

    def __init__(self):
        self.root = None
        self.size = 0          # number of distinct keys (nodes)
        self.comparisons = 0   # running total of node visits; callers diff it

    def insert(self, key, value):
        if self.root is None:
            self.root = Node(key, value)
            self.size += 1
            return
        node = self.root
        while True:
            self.comparisons += 1
            if key == node.key:
                node.values.append(value)
                return
            if key < node.key:
                if node.left is None:
                    node.left = Node(key, value)
                    self.size += 1
                    return
                node = node.left
            else:
                if node.right is None:
                    node.right = Node(key, value)
                    self.size += 1
                    return
                node = node.right

    def search(self, key):
        """Return the list of records stored under key, or None."""
        node = self.root
        while node is not None:
            self.comparisons += 1
            if key == node.key:
                return node.values
            node = node.left if key < node.key else node.right
        return None

    def iter_from(self, key):
        """Yield nodes in sorted order, starting at the first key >= `key`.

        Costs O(height) to find the start, then O(1) amortised per node.
        This powers both prefix suggestions and the 'top 5 more endangered'
        lookup.
        """
        stack = []
        node = self.root
        while node is not None:
            self.comparisons += 1
            if key <= node.key:
                stack.append(node)
                node = node.left
            else:
                node = node.right
        while stack:
            node = stack.pop()
            self.comparisons += 1
            yield node
            child = node.right
            while child is not None:
                stack.append(child)
                child = child.left

    def height(self):
        if self.root is None:
            return 0
        best, stack = 0, [(self.root, 1)]
        while stack:
            node, depth = stack.pop()
            best = max(best, depth)
            if node.left:
                stack.append((node.left, depth + 1))
            if node.right:
                stack.append((node.right, depth + 1))
        return best