import os
import unittest
from datetime import datetime
from unittest.mock import MagicMock
from lostfilm.models import Episode
from lostfilm.storage import Storage
from lostfilm.scheduler import Scheduler


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.db_path = "test_lostfilm.db"
        self.storage = Storage(self.db_path)

    def tearDown(self):
        if os.path.exists(self.db_path):
            os.remove(self.db_path)

    def test_init_db(self):
        self.assertTrue(os.path.exists(self.db_path))

    def test_store_and_get_episode(self):
        ep = Episode(
            id="123",
            title="Test Title",
            link="http://test.com",
            pub_date=datetime.now(),
        )
        is_new = self.storage.store_episode(ep)
        self.assertTrue(is_new)

        # Store again - should be False
        is_new = self.storage.store_episode(ep)
        self.assertFalse(is_new)

        # Get by id
        stored_ep = self.storage.get_episode_by_id("123")
        self.assertEqual(stored_ep.title, "Test Title")
        self.assertEqual(stored_ep.id, "123")

    def test_get_episodes(self):
        ep1 = Episode(id="1", title="Title 1", link="L1", pub_date=datetime(2023, 1, 1))
        ep2 = Episode(id="2", title="Title 2", link="L2", pub_date=datetime(2023, 1, 2))
        self.storage.store_episodes([ep1, ep2])

        eps = self.storage.get_episodes()
        self.assertEqual(len(eps), 2)
        self.assertEqual(eps[0].id, "2")  # Newest first


class TestScheduler(unittest.TestCase):
    def test_check_once(self):
        client = MagicMock()
        storage = MagicMock()

        ep = Episode(id="1", title="T1", link="L1", pub_date=datetime.now())
        client.fetch_favorites_feed.return_value = [ep]
        storage.store_episodes.return_value = 1

        scheduler = Scheduler(client, storage, interval_seconds=10)
        scheduler.check_once()

        client.fetch_favorites_feed.assert_called_once()
        storage.store_episodes.assert_called_with([ep])
