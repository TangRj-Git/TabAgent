"""只复制合法 JSON 参数；Schema 的业务校验仍由 MCP 服务端负责。"""

import math
from typing import Any

from .exceptions import MCPRequestError


def copy_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """
    校验并递归复制 MCP 工具调用参数。

    主要作用：
    1. 最外层必须是字典；None 按空参数处理。
    2. 只允许 JSON 兼容的数据类型，且所有字典的键必须是字符串。
    3. 拒绝 NaN、正无穷、负无穷等非有限浮点数。
    4. 限制嵌套深度，并检测字典、列表之间的循环引用。
    5. 为所有字典和列表创建副本，避免继续共享调用者传入的可变容器。

    返回值仍然是 Python 字典，不是 JSON 字符串。
    这里只校验基础数据结构，不校验具体工具的 inputSchema。
    """
    # 没有提供参数时，返回一个新的空字典。
    if arguments is None:
        return {}

    # 类型注解不会自动执行运行时校验，因此需要显式检查。
    # 最外层必须是字典；列表虽然可以出现在参数内部，但不能作为最外层参数。
    # 字典的键是否为字符串，会在下面的递归函数中检查。
    if not isinstance(arguments, dict):
        raise MCPRequestError("Tool arguments must be an object with string keys.")

    # 保存当前递归路径上正在处理的容器的对象身份标识，用于检测循环引用。
    # 这里只记录当前路径，不是记录所有曾经访问过的对象。
    # 所有递归调用共享这个集合，进入容器时添加，退出容器时移除。
    ancestors: set[int] = set()

    def copy(value: Any, depth: int) -> Any:
        """
        检查并复制当前值。

        value：当前处理的值，可以是容器，也可以是简单值。
        depth：当前嵌套深度；最外层为 0，每进入一个子值就加 1。
        """
        # 限制嵌套深度，避免过度嵌套带来的递归和资源开销。
        # depth == 64 仍然允许，depth > 64 才报错。
        # 这个检查对所有值生效，包括字典、列表和简单值。
        if depth > 64:
            raise MCPRequestError("Tool arguments exceed the maximum JSON nesting depth of 64.")

        # None、字符串、布尔值和整数都是允许的 JSON 简单值。
        # 这些值不可变，可以直接返回，不需要创建新的容器。
        if value is None or isinstance(value, (str, bool, int)):
            return value

        # 普通浮点数可以使用，但标准 JSON 不支持 NaN 和正负无穷。
        if isinstance(value, float):
            # math.isfinite() 判断数值是否有限。
            if not math.isfinite(value):
                raise MCPRequestError("Tool arguments must not contain non-finite numbers.")
            return value

        # 简单值已经处理完毕，剩下的合法类型只能是字典或列表。
        # tuple、set、bytes、自定义对象等类型都会被拒绝。
        if not isinstance(value, (dict, list)):
            raise MCPRequestError("Tool arguments must contain only JSON objects, arrays and scalar values.")

        # 获取当前容器的对象身份标识。
        # 用它判断是否遇到了同一个对象，而不是判断两个对象的内容是否相等。
        identity = id(value)

        # 如果当前容器已经出现在递归路径上，说明它直接或间接引用了自身。
        # 例如：data = {}; data["self"] = data。
        # 这种循环引用无法表示为普通 JSON，必须拒绝。
        if identity in ancestors:
            raise MCPRequestError("Tool arguments must not contain circular references.")

        # 开始处理当前容器，将其登记到当前递归路径。
        ancestors.add(identity)

        try:
            if isinstance(value, list):
                # 创建新列表，并递归检查、复制其中的每一个元素。
                # 元素属于下一层，因此 depth 加 1。
                return [copy(item, depth + 1) for item in value]

            # 到这里，value 一定是字典。
            # 直接遍历字典得到的是键；只要存在一个非字符串键，就拒绝。
            # 例如 {"name": "Alice"} 合法，{1: "Alice"} 不合法。
            if any(not isinstance(key, str) for key in value):
                raise MCPRequestError("All JSON object keys in tool arguments must be strings.")

            # 创建新字典。
            # 键已经确认是不可变的字符串，可以直接使用；
            # 每个值都进入下一层，继续递归检查和复制。
            return {key: copy(item, depth + 1) for key, item in value.items()}

        finally:
            # 无论正常 return，还是递归过程中抛出异常，都执行这里。
            # 离开当前容器时，将其从当前递归路径中移除。
            #
            # 这样，同一个容器被不同分支引用时，不会被误判为循环引用。
            # 例如 {"first": shared, "second": shared}：
            # 处理完 first 后会移除 shared 的标识，second 就可以正常处理。
            # 两个分支最终会得到各自独立的容器副本。
            ancestors.remove(identity)

    # 从最外层参数字典开始递归，初始深度为 0。
    # 校验成功时返回复制后的字典；不合法时抛出 MCPRequestError。
    return copy(arguments, 0)
