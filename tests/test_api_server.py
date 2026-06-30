"""API server 安全回归。

锁定 token 校验用常量时间比较（防时序侧信道），并保留：无配置 token 时放行、
token 不匹配时拒绝。可独立运行，无网络/LLM 依赖。
"""
from __future__ import annotations

import unittest

import api_server


class TokenIsValidTests(unittest.TestCase):
    def test_no_expected_token_allows_through(self) -> None:
        # 未配置 token（本地无鉴权场景）→ 任意请求放行
        self.assertTrue(api_server.token_is_valid("", {api_server.TOKEN_HEADER: "x"}, {}))
        self.assertTrue(api_server.token_is_valid("", {}, {}))

    def test_matching_header_token_accepted(self) -> None:
        token = "s3cret-token-abc"
        headers = {api_server.TOKEN_HEADER: token}
        self.assertTrue(api_server.token_is_valid(token, headers, {}))

    def test_mismatching_header_token_rejected(self) -> None:
        token = "s3cret-token-abc"
        headers = {api_server.TOKEN_HEADER: "wrong"}
        self.assertFalse(api_server.token_is_valid(token, headers, {}))

    def test_missing_header_token_rejected(self) -> None:
        token = "s3cret-token-abc"
        self.assertFalse(api_server.token_is_valid(token, {}, {}))

    def test_comparison_uses_constant_time_function(self) -> None:
        """S1 回归：token 须走 hmac.compare_digest，而非字符串 == 短路。

        解析源码确认比较路径常量时间：compare_digest 的核心约束是『两串等长才比较内容、
        否则恒为 False 但耗时与内容无关』；等长内容相同须接受、不同须拒绝。
        """
        import inspect
        src = inspect.getsource(api_server.token_is_valid)
        self.assertIn("compare_digest", src)  # 实现里含常量时间比较
        self.assertNotIn("== expected_token", src)  # 不再裸用 == 比较整串

    def test_equal_length_but_different_token_rejected(self) -> None:
        # compare_digest 对等长但内容不同的串恒 False（也是 == 短路会误判的场景）
        token = "aaaaaaaaaaaaaaaa"
        headers = {api_server.TOKEN_HEADER: "aaaaaaaaaaaaaaab"}  # 同长度末字节不同
        self.assertFalse(api_server.token_is_valid(token, headers, {}))


if __name__ == "__main__":
    unittest.main()
