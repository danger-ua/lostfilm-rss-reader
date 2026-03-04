"""Integration tests for the CLI (cli.py)."""

import json
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch


from lostfilm.exceptions import (
    AuthenticationError,
    ParseError,
    RateLimitError,
    ServerError,
)
from lostfilm.models import Episode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_episode(
    ep_id="11111",
    title="Test Show [S01E01] [720p]",
    link="http://www.lostfilm.tv/eps/11111",
    pub_date=None,
):
    return Episode(
        id=ep_id,
        title=title,
        link=link,
        pub_date=pub_date or datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
    )


def run_cli(*args, env=None):
    """
    Run the CLI main() with the given argv and return (stdout, stderr, exit_code).
    env is an optional dict of extra environment variables.
    """
    import os
    from io import StringIO

    import lostfilm.cli as cli_module

    base_env = {"LOSTFILM_UID": "test_uid", "LOSTFILM_USESS": "test_sess"}
    if env:
        base_env.update(env)

    stdout_capture = StringIO()
    stderr_capture = StringIO()
    exit_code = 0

    with (
        patch.dict(os.environ, base_env, clear=False),
        patch("sys.argv", ["lostfilm", *args]),
        patch("sys.stdout", stdout_capture),
        patch("sys.stderr", stderr_capture),
    ):
        try:
            cli_module.main()
        except SystemExit as e:
            exit_code = e.code if e.code is not None else 0

    return stdout_capture.getvalue(), stderr_capture.getvalue(), exit_code


# ---------------------------------------------------------------------------
# No command
# ---------------------------------------------------------------------------


class TestNoCommand:
    def test_exits_with_code_1(self):
        _stdout, _stderr, code = run_cli()
        assert code == 1


# ---------------------------------------------------------------------------
# list-favorites — normal output
# ---------------------------------------------------------------------------


class TestListFavoritesTable:
    def _run_with_episodes(self, episodes, *extra_args):
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_favorites_feed.return_value = episodes
            return run_cli("list-favorites", *extra_args)

    def test_exits_zero_on_success(self):
        episodes = [_make_episode()]
        _stdout, _stderr, code = self._run_with_episodes(episodes)
        assert code == 0

    def test_episode_title_appears_in_output(self):
        episodes = [_make_episode(title="Unique Show Title [S01E01]")]
        stdout, _stderr, _code = self._run_with_episodes(episodes)
        assert "Unique Show Title" in stdout

    def test_limit_restricts_rows(self):
        episodes = [
            _make_episode(ep_id=str(i), title=f"Show {i} [S01E0{i}]") for i in range(5)
        ]
        stdout, _stderr, _code = self._run_with_episodes(episodes, "--limit", "2")
        # "Show 0" and "Show 1" should appear, "Show 4" should not
        assert "Show 0" in stdout
        assert "Show 4" not in stdout

    def test_episodes_sorted_newest_first(self):
        older = _make_episode(
            ep_id="1", title="Old Show", pub_date=datetime(2020, 1, 1)
        )
        newer = _make_episode(
            ep_id="2", title="New Show", pub_date=datetime(2024, 1, 1)
        )
        stdout, _stderr, _code = self._run_with_episodes([older, newer])
        # "New Show" should appear before "Old Show" in the output
        assert stdout.index("New Show") < stdout.index("Old Show")


# ---------------------------------------------------------------------------
# list-favorites --json
# ---------------------------------------------------------------------------


class TestListFavoritesJson:
    def _run_json(self, episodes, *extra_args):
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_favorites_feed.return_value = episodes
            return run_cli("list-favorites", "--json", *extra_args)

    def test_output_is_valid_json(self):
        episodes = [_make_episode()]
        stdout, _stderr, _code = self._run_json(episodes)
        # stdout contains rich table AND printed JSON; find the JSON array
        json_start = stdout.find("[")
        data = json.loads(stdout[json_start:])
        assert isinstance(data, list)

    def test_json_contains_expected_fields(self):
        episodes = [_make_episode()]
        stdout, _stderr, _code = self._run_json(episodes)
        json_start = stdout.find("[")
        data = json.loads(stdout[json_start:])
        assert "id" in data[0]
        assert "title" in data[0]
        assert "download_url" in data[0]

    def test_json_limit_is_respected(self):
        episodes = [_make_episode(ep_id=str(i)) for i in range(5)]
        stdout, _stderr, code = self._run_json(episodes, "--limit", "2")
        json_start = stdout.find("[")
        data = json.loads(stdout[json_start:])
        assert len(data) == 2


# ---------------------------------------------------------------------------
# get-download-url
# ---------------------------------------------------------------------------


class TestGetDownloadUrl:
    def test_prints_url_with_id(self):
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.get_download_url.return_value = (
                "https://n.tracktor.site/rssdownloader.php?id=99999"
            )
            stdout, _stderr, code = run_cli("get-download-url", "99999")
        assert "99999" in stdout
        assert code == 0

    def test_calls_client_with_item_id(self):
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.get_download_url.return_value = (
                "https://n.tracktor.site/rssdownloader.php?id=42"
            )
            run_cli("get-download-url", "42")
            instance.get_download_url.assert_called_once_with("42")


# ---------------------------------------------------------------------------
# Error handling — list-favorites
# ---------------------------------------------------------------------------


class TestListFavoritesErrors:
    def _run_with_error(self, exc):
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.fetch_favorites_feed.side_effect = exc
            return run_cli("list-favorites")

    def test_authentication_error_exits_1(self):
        _stdout, _stderr, code = self._run_with_error(
            AuthenticationError("session expired")
        )
        assert code == 1

    def test_server_error_exits_1(self):
        _stdout, _stderr, code = self._run_with_error(ServerError("service down"))
        assert code == 1

    def test_rate_limit_error_exits_1(self):
        _stdout, _stderr, code = self._run_with_error(RateLimitError("too fast"))
        assert code == 1

    def test_parse_error_exits_1(self):
        _stdout, _stderr, code = self._run_with_error(ParseError("bad xml"))
        assert code == 1

    def test_unexpected_error_exits_1(self):
        _stdout, _stderr, code = self._run_with_error(
            RuntimeError("totally unexpected")
        )
        assert code == 1


# ---------------------------------------------------------------------------
# Error handling — get-download-url
# ---------------------------------------------------------------------------


class TestGetDownloadUrlErrors:
    def test_lostfilm_error_exits_1(self):
        from lostfilm.exceptions import LostFilmError

        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.get_download_url.side_effect = LostFilmError("generic failure")
            _stdout, _stderr, code = run_cli("get-download-url", "123")
        assert code == 1

    def test_unexpected_error_exits_1(self):
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.get_download_url.side_effect = RuntimeError("oops")
            _stdout, _stderr, code = run_cli("get-download-url", "123")
        assert code == 1


# ---------------------------------------------------------------------------
# download
# ---------------------------------------------------------------------------


class TestDownloadCommand:
    def test_calls_client_download_torrent(self, tmp_path):
        output_file = tmp_path / "test.torrent"
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.download_torrent.return_value = b"mock torrent file"

            # Use patch for the open-builtin inside the cli module's download function
            # Or just let it write to the tmp_path since we control it
            stdout, _stderr, code = run_cli(
                "download", "12345", "--output", str(output_file)
            )

        assert code == 0
        assert instance.download_torrent.called
        assert output_file.read_bytes() == b"mock torrent file"
        assert "Successfully downloaded" in stdout

    def test_default_output_filename(self, tmp_path):
        # Change CWD to tmp_path to test default filename creation
        import os

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with patch("lostfilm.cli.LostFilmClient") as MockClient:
                instance = MockClient.return_value
                instance.get_episode_by_id.return_value = None
                instance.download_torrent.return_value = b"data"
                run_cli("download", "999")

            expected_file = tmp_path / "999.torrent"
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"data"
        finally:
            os.chdir(old_cwd)

    def test_download_error_exits_1(self):
        from lostfilm.exceptions import LostFilmError

        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.download_torrent.side_effect = LostFilmError("fail")
            _stdout, _stderr, code = run_cli("download", "123")
        assert code == 1

    def test_uses_title_for_filename(self, tmp_path):
        import os

        old_cwd = os.getcwd()
        os.chdir(tmp_path)
        try:
            with patch("lostfilm.cli.LostFilmClient") as MockClient:
                instance = MockClient.return_value
                mock_ep = MagicMock(spec=Episode)
                mock_ep.title = "Cool Show [S01E01] (720p)"
                instance.get_episode_by_id.return_value = mock_ep
                instance.download_torrent.return_value = b"torrent_data"

                run_cli("download", "12345")

            # Expected: "Cool_Show__S01E01___720p_.torrent" (simplified: sanitized)
            # Actually our sanitizer: re.sub(r'[\\/*?:"<>|]', "_", filename).replace(" ", "_").replace("(", "").replace(")", "")
            # "Cool Show [S01E01] (720p)" -> "Cool_Show_[S01E01]_720p"
            expected_filename = "Cool_Show_[S01E01]_720p.torrent"
            expected_file = tmp_path / expected_filename
            assert expected_file.exists()
            assert expected_file.read_bytes() == b"torrent_data"
        finally:
            os.chdir(old_cwd)

    def test_sanitize_filename(self):
        from lostfilm.cli import sanitize_filename

        assert sanitize_filename("Show Name (2024)") == "Show_Name_2024"
        assert sanitize_filename("Show/Name:?*") == "Show_Name___"
        assert sanitize_filename("Show [S01E01] 720p") == "Show_[S01E01]_720p"


class TestCheckAuthCommand:
    def test_success_prints_credentials(self):
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.validate_credentials.return_value = True
            instance.uid = "test_uid"
            instance.usess = "test_sess"

            stdout, _stderr, code = run_cli("check-auth")

        assert code == 0
        assert "Authentication successful" in stdout
        assert "test_uid" in stdout
        assert "test_sess" in stdout

    def test_failure_exits_1(self):
        with patch("lostfilm.cli.LostFilmClient") as MockClient:
            instance = MockClient.return_value
            instance.validate_credentials.return_value = False

            _stdout, _stderr, code = run_cli("check-auth")

        assert code == 1
