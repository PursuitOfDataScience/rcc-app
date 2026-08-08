"""The scrubber is a security control, so it is tested like one.

Users of an HPC assistant paste job scripts, logs and `.bashrc` fragments. The
cases below are the shapes that actually turn up.
"""

import pytest

from sage import scrub


class TestSecrets:
    @pytest.mark.parametrize(
        "text",
        [
            "export MISTRAL_API_KEY=sk-abcdefghijklmnopqrstuvwx",
            "OPENCODE_API_KEY=sk-zen-abcdefghijklmnopqrst",
            "token: ghp_abcdefghijklmnopqrstuvwxyz012345",
            "aws key AKIAIOSFODNN7EXAMPLE here",
            "Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
            "password: hunter2xyz",
            "curl --password=letmein123 https://example.com",
            "slack xoxb-123456789012-abcdefghijkl",
            "gitlab glpat-abcdefghijklmnopqrst",
        ],
    )
    def test_credentials_do_not_survive(self, text):
        out = scrub.scrub(text)
        assert not scrub.contains_secret(out), out

    def test_a_private_key_block_is_removed_whole(self):
        text = (
            "-----BEGIN OPENSSH PRIVATE KEY-----\n"
            "b3BlbnNzaC1rZXktdjEAAAAA\nmore\n"
            "-----END OPENSSH PRIVATE KEY-----"
        )
        assert scrub.scrub(text) == "<PRIVATE_KEY>"

    def test_a_jwt_does_not_survive(self):
        text = "cookie eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NX0.abcdefghijk"
        assert "eyJhbGci" not in scrub.scrub(text)

    def test_the_user_can_be_warned_about_their_own_paste(self):
        assert scrub.looks_like_secret("here is sk-zen-abcdefghijklmnop1234")
        assert not scrub.looks_like_secret("here is my sbatch script")


class TestIdentifiers:
    def test_home_and_project_paths_are_generalised(self):
        out = scrub.scrub("cd /home/jsmith && ls /project2/pi-alice/jsmith")
        assert "jsmith" not in out
        assert "pi-alice" not in out
        assert "<CNETID>" in out

    def test_scratch_paths_are_generalised(self):
        out = scrub.scrub("cp data /scratch/midway3/jsmith/out")
        assert "jsmith" not in out

    def test_emails_and_ips_go(self):
        out = scrub.scrub("mail jsmith@uchicago.edu from 10.150.1.22")
        assert "jsmith@uchicago.edu" not in out
        assert "10.150.1.22" not in out


class TestWhatMustSurvive:
    """Redaction that eats the diagnosis is not worth having: job ids, partition
    names, module names and error strings are not identifying and are most of the
    value in a pasted log."""

    @pytest.mark.parametrize(
        "text",
        [
            "job 12345678 failed",
            "partition caslake is full",
            "module load python/anaconda-2022.05",
            "slurmstepd: error: exceeded memory limit, being killed",
            "sbatch --gres=gpu:1 --time=36:00:00",
            "State=OUT_OF_MEMORY ExitCode=0:125",
        ],
    )
    def test_diagnostic_text_is_untouched(self, text):
        assert scrub.scrub(text) == text


class TestFailureModes:
    def test_empty_input_is_empty_output(self):
        assert scrub.scrub("") == ""
        assert not scrub.contains_secret("")

    def test_it_never_raises(self):
        for value in (None, 12345, [], {"a": 1}):
            assert isinstance(scrub.scrub(value), str)

    def test_placeholders_keep_the_sentence_readable(self):
        """Replace, don't delete: a redacted question must still be groupable."""
        out = scrub.scrub("why can't I write to /home/jsmith when over quota")
        assert out.startswith("why can't I write to ")
        assert out.endswith(" when over quota")
