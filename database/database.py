import motor.motor_asyncio
import base64
import logging
from datetime import datetime, timedelta, date
from typing import List, Optional
from config import * 
import modectx

logging.basicConfig(level=logging.INFO)


class Master:
    def __init__(self, DB_URL, DB_NAME):
        self.dbclient = motor.motor_asyncio.AsyncIOMotorClient(DB_URL)
        self.database = self.dbclient[DB_NAME]

        # Initialize all collections
        self.user_data = self.database['users']
        self.channel_data = self.database['channels']
        self.admins_data = self.database['admins']
        self.del_timer_data = self.database['del_timer']
        self.ban_data = self.database['ban_data']
        self.rqst_fsub_data = self.database['request_forcesub']
        self.rqst_fsub_Channel_data = self.database['request_forcesub_channel']
        self.broadcast_data = self.database['channel_broadcast']

        # Main collection reference (for backward compatibility)
        self.col = self.user_data

    # ── Link mode (A/B): B mode ki settings alag collections mein ──────────
    def _c(self, name: str):
        """Mirrored collection: mode B mein '<name>_b', warna '<name>'."""
        return self.database[name + "_b"] if modectx.cur() == "b" else self.database[name]

    def _us(self):
        """Per-user flow state (ads-free, link pos, fsub pending...) — B mode ka alag collection."""
        return self.database['users_b'] if modectx.cur() == "b" else self.user_data

    @property
    def fsub_data(self):
        return self._c('fsub')

    def new_user(self, id, username=None):
        return dict(
            _id=int(id),
            username=username.lower() if username else None,
            join_date=date.today().isoformat(),
            ban_status=dict(
                is_banned=False,
                ban_duration=0,
                banned_on=date.max.isoformat(),
                ban_reason='',
            )
        )

    async def add_user(self, b, m):
        u = m.from_user
        if not await self.is_user_exist(u.id):
            user = self.new_user(u.id, u.username)
            try:
                await self.user_data.insert_one(user)
                logging.info(f"New user added: {u.id}")
                # Uncomment if send_log function exists
                # await send_log(b, u)
            except Exception as e:
                logging.error(f"Error adding user {u.id}: {e}")
        else:
            logging.info(f"User {u.id} already exists")

    async def is_user_exist(self, id):
        try:
            user = await self.user_data.find_one({"_id": int(id)})
            return bool(user)
        except Exception as e:
            logging.error(f"Error checking if user {id} exists: {e}")
            return False

    async def get_all_users(self):
        try:
            all_users = self.user_data.find({})
            return all_users
        except Exception as e:
            logging.error(f"Error getting all users: {e}")
            return None

    async def total_users_count(self):
        try:
            count = await self.user_data.count_documents({})
            return count
        except Exception as e:
            logging.error(f"Error counting users: {e}")
            return 0

    async def delete_user(self, user_id):
        try:
            await self.user_data.delete_many({"_id": int(user_id)})
        except Exception as e:
            logging.error(f"Error deleting user {user_id}: {e}")

    async def is_user_banned(self, user_id):
        try:
            user = await self.ban_data.find_one({"_id": user_id})
            if user and user.get("ban_status", {}).get("is_banned", False):
                return user
        except Exception as e:
            logging.error(f"Error in checking ban status {user_id}: {e}")

    async def is_admin(self, user_id: int) -> bool:
        """Check if a user is an admin."""
        try:
            _id = int(user_id)
            return bool(await self.admins_data.find_one({"_id": user_id}))
        except Exception as e:
            logging.error(f"Error checking admin status for {user_id}: {e}")
            return False

    async def add_admin(self, user_id: int) -> bool:
        """Add a user as admin."""
        try:
            _id = int(user_id)
            await self.admins_data.update_one(
                {"_id": user_id},
                {"$set": {"_id": user_id, "added_at": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error adding admin {user_id}: {e}")
            return False

    async def remove_admin(self, user_id: int) -> bool:
        """Remove a user from admins."""
        try:
            result = await self.admins_data.delete_one({"_id": user_id})
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"Error removing admin {user_id}: {e}")
            return False

    async def list_admins(self) -> list:
        """List all admin user IDs."""
        try:
            admins = await self.admins_data.find({}).to_list(None)
            return [admin["_id"] for admin in admins]
        except Exception as e:
            logging.error(f"Error listing admins: {e}")
            return []
            
    async def get_encoded_link(self, channel_id: int) -> Optional[str]:
        """Get the encoded link for a channel."""
        if not isinstance(channel_id, int):
            logging.error(f"Invalid channel_id: {channel_id}")
            return None

        try:
            channel = await self.channel_data.find_one({"channel_id": channel_id, "status": "active"})
            if channel and "encoded_link" in channel:
                logging.info(f"Retrieved encoded_link for channel {channel_id}: {channel['encoded_link']}")
                return channel["encoded_link"]
            else:
                logging.warning(f"No encoded_link found for channel {channel_id}")
                return None
        except Exception as e:
            logging.error(f"Error getting encoded link for channel {channel_id}: {e}")
            return None

    async def get_encoded_link2(self, channel_id: int) -> Optional[str]:
        """Get the secondary encoded link for a channel."""
        if not isinstance(channel_id, int):
            logging.error(f"Invalid channel_id: {channel_id}")
            return None

        try:
            channel = await self.channel_data.find_one({"channel_id": channel_id, "status": "active"})
            if channel and "req_encoded_link" in channel:
                logging.info(f"Retrieved req_encoded_link for channel {channel_id}: {channel['req_encoded_link']}")
                return channel["req_encoded_link"]
            else:
                logging.warning(f"No req_encoded_link found for channel {channel_id}")
                return None
        except Exception as e:
            logging.error(f"Error getting secondary encoded link for channel {channel_id}: {e}")
            return None

    async def save_channel(self, channel_id: int) -> bool:
        """Save a channel to the database with invite link expiration."""
        if not isinstance(channel_id, int):
            logging.error(f"Invalid channel_id: {channel_id}")
            return False

        try:
            # Generate encoded links using standard base64 encoding
            string_bytes = str(channel_id).encode("ascii")
            base64_bytes = base64.urlsafe_b64encode(string_bytes)
            encoded_link = (base64_bytes.decode("ascii")).strip("=")
            req_encoded_link = encoded_link  # Same encoding for both
            
            await self.channel_data.update_one(
                {"channel_id": channel_id},
                {
                    "$set": {
                        "channel_id": channel_id,
                        "encoded_link": encoded_link,
                        "req_encoded_link": req_encoded_link,
                        "invite_link_expiry": None,
                        "created_at": datetime.utcnow(),
                        "status": "active"
                    }
                },
                upsert=True
            )
            logging.info(f"Saved channel {channel_id} with encoded_link: {encoded_link}")
            return True
        except Exception as e:
            logging.error(f"Error saving channel {channel_id}: {e}")
            return False

    async def get_channels(self) -> List[int]:
        """Get all active channel IDs from the database."""
        try:
            channels = await self.channel_data.find({"status": "active"}).to_list(None)
            valid_channels = [ch["channel_id"] for ch in channels if "channel_id" in ch]
            if not valid_channels:
                logging.info(f"No valid channels found in database. Total documents checked: {len(channels)}")
            return valid_channels
        except Exception as e:
            logging.error(f"Error fetching channels: {e}")
            return []

    async def show_channels(self) -> List[int]:
        """Alias for get_channels - used by reqChannel_exist."""
        return await self.get_channels()

    async def delete_channel(self, channel_id: int) -> bool:
        """Delete a channel from the database."""
        try:
            result = await self.channel_data.delete_one({"channel_id": channel_id})
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"Error deleting channel {channel_id}: {e}")
            return False

    async def save_encoded_link(self, channel_id: int) -> Optional[str]:
        """Save an encoded link for a channel and return it."""
        if not isinstance(channel_id, int):
            logging.error(f"Invalid channel_id: {channel_id}")
            return None

        try:
            # Use the same encoding method as helper_func.py
            string_bytes = str(channel_id).encode("ascii")
            base64_bytes = base64.urlsafe_b64encode(string_bytes)
            encoded_link = (base64_bytes.decode("ascii")).strip("=")
            
            await self.channel_data.update_one(
                {"channel_id": channel_id},
                {
                    "$set": {
                        "channel_id": channel_id,
                        "encoded_link": encoded_link,
                        "status": "active",
                        "updated_at": datetime.utcnow()
                    }
                },
                upsert=True
            )
            logging.info(f"Saved encoded link for channel {channel_id}: {encoded_link}")
            return encoded_link
        except Exception as e:
            logging.error(f"Error saving encoded link for channel {channel_id}: {e}")
            return None

    async def get_channel_by_encoded_link(self, encoded_link: str) -> Optional[int]:
        """Get a channel ID by its encoded link - with fallback decoding."""
        if not isinstance(encoded_link, str):
            logging.error("get_channel_by_encoded_link: encoded_link is not a string")
            return None

        try:
            logging.info(f"[NORMAL LINK] Searching for channel with encoded_link: {encoded_link}")
            
            # First try: Search by encoded_link field
            channel = await self.channel_data.find_one({"encoded_link": encoded_link, "status": "active"})
            
            if channel and "channel_id" in channel:
                logging.info(f"[NORMAL LINK] Found channel by encoded_link: {channel['channel_id']}")
                return channel["channel_id"]
            
            # Second try: Decode the base64 string to get channel_id
            logging.warning(f"[NORMAL LINK] Not found in DB, trying to decode: {encoded_link}")
            try:
                # Use the same decoding method as helper_func.py
                base64_string = encoded_link.strip("=")
                base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
                string_bytes = base64.urlsafe_b64decode(base64_bytes)
                decoded_string = string_bytes.decode("ascii")
                decoded_id = int(decoded_string)
                logging.info(f"[NORMAL LINK] Successfully decoded channel_id: {decoded_id}")
                
                # Try to find channel by channel_id
                channel = await self.channel_data.find_one({"channel_id": decoded_id})
                
                if channel:
                    logging.info(f"[NORMAL LINK] Channel {decoded_id} exists in DB, updating encoded_link")
                    # Update the encoded_link field for this channel
                    await self.channel_data.update_one(
                        {"channel_id": decoded_id},
                        {
                            "$set": {
                                "encoded_link": encoded_link,
                                "status": "active",
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    return decoded_id
                else:
                    logging.warning(f"[NORMAL LINK] Channel {decoded_id} not found in DB, creating it")
                    # Create the channel entry using the same encoding
                    string_bytes = str(decoded_id).encode("ascii")
                    base64_bytes = base64.urlsafe_b64encode(string_bytes)
                    new_encoded_link = (base64_bytes.decode("ascii")).strip("=")
                    
                    await self.channel_data.update_one(
                        {"channel_id": decoded_id},
                        {
                            "$set": {
                                "channel_id": decoded_id,
                                "encoded_link": new_encoded_link,
                                "req_encoded_link": new_encoded_link,
                                "status": "active",
                                "created_at": datetime.utcnow()
                            }
                        },
                        upsert=True
                    )
                    return decoded_id
                    
            except Exception as decode_error:
                logging.error(f"[NORMAL LINK] Failed to decode base64 '{encoded_link}': {decode_error}")
            
            return None
            
        except Exception as e:
            logging.error(f"[NORMAL LINK] Error fetching channel by encoded link {encoded_link}: {e}")
            return None

    async def save_encoded_link2(self, channel_id: int, encoded_link: str) -> Optional[str]:
        """Save a secondary encoded link for a channel."""
        if not isinstance(channel_id, int) or not isinstance(encoded_link, str):
            logging.error(f"Invalid input: channel_id={channel_id}, encoded_link={encoded_link}")
            return None

        try:
            await self.channel_data.update_one(
                {"channel_id": channel_id},
                {
                    "$set": {
                        "channel_id": channel_id,
                        "req_encoded_link": encoded_link,
                        "status": "active",
                        "updated_at": datetime.utcnow()
                    }
                },
                upsert=True
            )
            logging.info(f"Saved req_encoded link for channel {channel_id}: {encoded_link}")
            return encoded_link
        except Exception as e:
            logging.error(f"Error saving secondary encoded link for channel {channel_id}: {e}")
            return None

    async def get_channel_by_encoded_link2(self, encoded_link: str) -> Optional[int]:
        """Get a channel ID by its secondary encoded link - with fallback decoding."""
        if not isinstance(encoded_link, str):
            logging.error("get_channel_by_encoded_link2: encoded_link is not a string")
            return None

        try:
            logging.info(f"[REQUEST LINK] Searching for channel with req_encoded_link: {encoded_link}")
            
            # First try: Search by req_encoded_link field
            channel = await self.channel_data.find_one({"req_encoded_link": encoded_link, "status": "active"})
            
            if channel and "channel_id" in channel:
                logging.info(f"[REQUEST LINK] Found channel by req_encoded_link: {channel['channel_id']}")
                return channel["channel_id"]
            
            # Second try: Decode the base64 string to get channel_id
            logging.warning(f"[REQUEST LINK] Not found in DB, trying to decode: {encoded_link}")
            try:
                # Use the same decoding method as helper_func.py
                base64_string = encoded_link.strip("=")
                base64_bytes = (base64_string + "=" * (-len(base64_string) % 4)).encode("ascii")
                string_bytes = base64.urlsafe_b64decode(base64_bytes)
                decoded_string = string_bytes.decode("ascii")
                decoded_id = int(decoded_string)
                logging.info(f"[REQUEST LINK] Successfully decoded channel_id: {decoded_id}")
                
                # Try to find channel by channel_id
                channel = await self.channel_data.find_one({"channel_id": decoded_id})
                
                if channel:
                    logging.info(f"[REQUEST LINK] Channel {decoded_id} exists in DB, updating req_encoded_link")
                    # Update the req_encoded_link field for this channel
                    await self.channel_data.update_one(
                        {"channel_id": decoded_id},
                        {
                            "$set": {
                                "req_encoded_link": encoded_link,
                                "status": "active",
                                "updated_at": datetime.utcnow()
                            }
                        }
                    )
                    return decoded_id
                else:
                    logging.warning(f"[REQUEST LINK] Channel {decoded_id} not found in DB, creating it")
                    # Create the channel entry using the same encoding
                    string_bytes = str(decoded_id).encode("ascii")
                    base64_bytes = base64.urlsafe_b64encode(string_bytes)
                    new_encoded_link = (base64_bytes.decode("ascii")).strip("=")
                    
                    await self.channel_data.update_one(
                        {"channel_id": decoded_id},
                        {
                            "$set": {
                                "channel_id": decoded_id,
                                "encoded_link": new_encoded_link,
                                "req_encoded_link": new_encoded_link,
                                "status": "active",
                                "created_at": datetime.utcnow()
                            }
                        },
                        upsert=True
                    )
                    return decoded_id
                    
            except Exception as decode_error:
                logging.error(f"[REQUEST LINK] Failed to decode base64 '{encoded_link}': {decode_error}")
            
            return None
            
        except Exception as e:
            logging.error(f"[REQUEST LINK] Error fetching channel by secondary encoded link {encoded_link}: {e}")
            return None

    async def save_invite_link(self, channel_id: int, invite_link: str, is_request: bool) -> bool:
        """Save the current invite link for a channel and its type."""
        if not isinstance(channel_id, int) or not isinstance(invite_link, str):
            logging.error(f"Invalid input: channel_id={channel_id}, invite_link={invite_link}")
            return False

        try:
            await self.channel_data.update_one(
                {"channel_id": channel_id},
                {
                    "$set": {
                        "current_invite_link": invite_link,
                        "is_request_link": is_request,
                        "invite_link_created_at": datetime.utcnow(),
                        "status": "active"
                    }
                },
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error saving invite link for channel {channel_id}: {e}")
            return False

    async def get_current_invite_link(self, channel_id: int) -> Optional[dict]:
        """Get the current invite link and its type for a channel."""
        if not isinstance(channel_id, int):
            return None

        try:
            channel = await self.channel_data.find_one({"channel_id": channel_id, "status": "active"})
            if channel and "current_invite_link" in channel:
                return {
                    "invite_link": channel["current_invite_link"],
                    "is_request": channel.get("is_request_link", False)
                }
            return None
        except Exception as e:
            logging.error(f"Error fetching current invite link for channel {channel_id}: {e}")
            return None

    async def clear_invite_link(self, channel_id: int) -> bool:
        """Remove the cached invite-link fields for a channel (after it's been revoked)."""
        if not isinstance(channel_id, int):
            return False
        try:
            await self.channel_data.update_one(
                {"channel_id": channel_id},
                {"$unset": {
                    "current_invite_link": "",
                    "is_request_link": "",
                    "invite_link_created_at": ""
                }}
            )
            return True
        except Exception as e:
            logging.error(f"Error clearing invite link for channel {channel_id}: {e}")
            return False

    async def add_fsub_channel(self, channel_id: int, custom_name: str = None) -> bool:
        """Add a channel to the FSub list.

        Naye channels hamesha REQUEST mode ("on") mein add hote hain by default —
        normal fsub nahi. Chahiye toh baad mein /togglereq ya settings panel se
        "off" (normal join) mein switch kiya ja sakta hai.
        """
        if not isinstance(channel_id, int):
            logging.error(f"Invalid channel_id: {channel_id}")
            return False

        try:
            set_data = {
                "channel_id": channel_id,
                "created_at": datetime.utcnow(),
                "status": "active",
                "mode": "on"
            }
            if custom_name:
                set_data["custom_name"] = custom_name.strip()

            result = await self.fsub_data.update_one(
                {"channel_id": channel_id},
                {"$set": set_data},
                upsert=True
            )
            return result.matched_count == 0
        except Exception as e:
            logging.error(f"Error adding FSub channel {channel_id}: {e}")
            return False

    async def set_fsub_channel_name(self, channel_id: int, custom_name: str) -> bool:
        """Set a custom display name for a FSub channel button."""
        try:
            await self.fsub_data.update_one(
                {"channel_id": channel_id},
                {"$set": {"custom_name": custom_name.strip()}},
                upsert=False
            )
            return True
        except Exception as e:
            logging.error(f"Error setting custom name for {channel_id}: {e}")
            return False

    async def get_fsub_channel_name(self, channel_id: int) -> str | None:
        """Get custom name of a FSub channel (None if not set)."""
        try:
            data = await self.fsub_data.find_one({"channel_id": channel_id})
            return data.get("custom_name") if data else None
        except Exception as e:
            logging.error(f"Error fetching custom name for {channel_id}: {e}")
            return None

    async def increment_fsub_join_count(self, channel_id: int) -> bool:
        """Fsub ke through channel join hone par counter +1 (bot ke fsub se hua join)."""
        try:
            await self.fsub_data.update_one(
                {"channel_id": channel_id},
                {"$inc": {"join_count": 1}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error incrementing fsub join_count for {channel_id}: {e}")
            return False

    async def increment_fsub_request_count(self, channel_id: int) -> bool:
        """Fsub ke through join REQUEST aane par counter +1 (bot ke fsub se hua request)."""
        try:
            await self.fsub_data.update_one(
                {"channel_id": channel_id},
                {"$inc": {"request_count": 1}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error incrementing fsub request_count for {channel_id}: {e}")
            return False

    async def get_fsub_stats(self, channel_id: int) -> dict:
        """Get join_count & request_count (bot ke fsub ki madad se hue) for a channel."""
        try:
            data = await self.fsub_data.find_one({"channel_id": channel_id})
            return {
                "join_count": data.get("join_count", 0) if data else 0,
                "request_count": data.get("request_count", 0) if data else 0,
            }
        except Exception as e:
            logging.error(f"Error fetching fsub stats for {channel_id}: {e}")
            return {"join_count": 0, "request_count": 0}

    async def remove_fsub_channel(self, channel_id: int) -> bool:
        """Remove a channel from the FSub list."""
        try:
            result = await self.fsub_data.delete_one({"channel_id": channel_id})
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"Error removing FSub channel {channel_id}: {e}")
            return False

    async def get_fsub_channels(self) -> List[int]:
        """Get all active FSub channel IDs, oldest-added first.

        Sorted by created_at so channel position (1st added, 2nd added, ...)
        stays stable — used for default button naming (Join/Request channel 01, 02...).
        """
        try:
            channels = await self.fsub_data.find({"status": "active"}).sort("created_at", 1).to_list(None)
            return [channel["channel_id"] for channel in channels if "channel_id" in channel]
        except Exception as e:
            logging.error(f"Error fetching FSub channels: {e}")
            return []

    async def get_channel_mode(self, channel_id: int):
        """Get current mode of a channel."""
        data = await self.fsub_data.find_one({'channel_id': channel_id})
        return data.get("mode", "off") if data else "off"

    async def set_channel_mode(self, channel_id: int, mode: str):
        """Set mode of a channel."""
        await self.fsub_data.update_one(
            {'channel_id': channel_id},
            {'$set': {'mode': mode}},
            upsert=True
        )

    async def set_channel_mode_all(self, mode: str) -> dict:
        """
        Set mode for all FSub channels at once.

        Args:
            mode: The mode to set ('on' or 'off')

        Returns:
            dict: Result with success status and count of updated channels
        """
        try:
            # Validate mode
            if mode not in ['on', 'off']:
                logging.error(f"Invalid mode: {mode}. Must be 'on' or 'off'")
                return {
                    "success": False,
                    "updated_count": 0,
                    "message": "Invalid mode. Must be 'on' or 'off'"
                }

            # Update all active FSub channels
            result = await self.fsub_data.update_many(
                {"status": "active"},
                {
                    "$set": {
                        "mode": mode,
                        "mode_updated_at": datetime.utcnow()
                    }
                }
            )

            logging.info(f"Bulk mode update: Set {result.modified_count} channels to '{mode}' mode")

            return {
                "success": True,
                "updated_count": result.modified_count,
                "matched_count": result.matched_count,
                "message": f"Successfully set {result.modified_count} channel(s) to '{mode}' mode"
            }

        except Exception as e:
            logging.error(f"Error setting mode for all channels: {e}")
            return {
                "success": False,
                "updated_count": 0,
                "message": f"Error: {str(e)}"
            }

    async def get_channel_mode_all(self) -> dict:
        """
        Get the mode status of all FSub channels.

        Returns:
            dict: Contains mode statistics and list of channels with their modes
        """
        try:
            channels = await self.fsub_data.find({"status": "active"}).to_list(None)

            if not channels:
                return {
                    "success": True,
                    "total_channels": 0,
                    "on_count": 0,
                    "off_count": 0,
                    "channels": [],
                    "message": "No FSub channels found"
                }

            channel_modes = []
            on_count = 0
            off_count = 0

            for channel in channels:
                channel_id = channel.get("channel_id")
                mode = channel.get("mode", "off")

                if mode == "on":
                    on_count += 1
                else:
                    off_count += 1

                channel_modes.append({
                    "channel_id": channel_id,
                    "mode": mode
                })

            return {
                "success": True,
                "total_channels": len(channels),
                "on_count": on_count,
                "off_count": off_count,
                "channels": channel_modes,
                "message": f"Found {len(channels)} channel(s): {on_count} ON, {off_count} OFF"
            }

        except Exception as e:
            logging.error(f"Error getting mode for all channels: {e}")
            return {
                "success": False,
                "total_channels": 0,
                "on_count": 0,
                "off_count": 0,
                "channels": [],
                "message": f"Error: {str(e)}"
            }

    async def req_user(self, channel_id: int, user_id: int):
        """Add the user to the set of users for a specific channel."""
        try:
            await self.rqst_fsub_Channel_data.update_one(
                {'channel_id': int(channel_id)},
                {'$addToSet': {'user_ids': int(user_id)}},
                upsert=True
            )
        except Exception as e:
            logging.error(f"[DB ERROR] Failed to add user to request list: {e}")

    async def del_req_user(self, channel_id: int, user_id: int):
        """Remove a user from the channel set."""
        await self.rqst_fsub_Channel_data.update_one(
            {'channel_id': channel_id},
            {'$pull': {'user_ids': user_id}}
        )

    async def req_user_exist(self, channel_id: int, user_id: int):
        """Check if the user exists in the set of the channel's users."""
        try:
            found = await self.rqst_fsub_Channel_data.find_one({
                'channel_id': int(channel_id),
                'user_ids': int(user_id)
            })
            return bool(found)
        except Exception as e:
            logging.error(f"[DB ERROR] Failed to check request list: {e}")
            return False

    async def reqChannel_exist(self, channel_id: int):
        """Check if a channel exists using show_channels."""
        channel_ids = await self.show_channels()
        return channel_id in channel_ids

    async def get_original_link(self, channel_id: int) -> Optional[str]:
        """Get the original link stored for a channel (used by /genlink)."""
        if not isinstance(channel_id, int):
            return None
        try:
            channel = await self.channel_data.find_one({"channel_id": channel_id, "status": "active"})
            return channel.get("original_link") if channel else None
        except Exception as e:
            logging.error(f"Error fetching original link for channel {channel_id}: {e}")
            return None

    # ==================== FAKE LINK FUNCTIONS ====================
    
    async def set_fake_link(self, url: str, button_text: str) -> bool:
        """Set fake link with button text."""
        try:
            await self._c('fake_link').update_one(
                {"_id": "fake_link_config"},
                {
                    "$set": {
                        "_id": "fake_link_config",
                        "url": url,
                        "button_text": button_text,
                        "enabled": True,
                        "updated_at": datetime.utcnow()
                    }
                },
                upsert=True
            )
            logging.info(f"Fake link set: {button_text} - {url}")
            return True
        except Exception as e:
            logging.error(f"Error setting fake link: {e}")
            return False

    async def get_fake_link(self) -> Optional[dict]:
        """Get fake link configuration."""
        try:
            config = await self._c('fake_link').find_one({"_id": "fake_link_config"})
            if config and config.get("enabled", False):
                return {
                    "url": config.get("url"),
                    "button_text": config.get("button_text")
                }
            return None
        except Exception as e:
            logging.error(f"Error getting fake link: {e}")
            return None

    async def remove_fake_link(self) -> bool:
        """Remove/disable fake link."""
        try:
            result = await self._c('fake_link').delete_one({"_id": "fake_link_config"})
            logging.info("Fake link removed")
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"Error removing fake link: {e}")
            return False

    # ── Multi Fake Link (Jojo system) ────────────────────────────
    # Each doc: {url, button_text, row, order}  (no fixed _id)

    async def add_fake_link(self, url: str, button_text: str, row: int = 1) -> bool:
        """Add a new fake link (multi-link support). Purana delete nahi hoga."""
        try:
            col = self._c('fake_link_multi')
            last = await col.find_one(sort=[("order", -1)])
            order = (last["order"] + 1) if last else 1
            await col.insert_one({
                "url": url,
                "button_text": button_text,
                "row": row,
                "order": order,
            })
            logging.info(f"add_fake_link: {button_text} -> {url} (row={row})")
            return True
        except Exception as e:
            logging.error(f"add_fake_link error: {e}")
            return False

    async def get_fake_links(self) -> list:
        """Return all fake links sorted by order."""
        try:
            col = self._c('fake_link_multi')
            cursor = col.find().sort("order", 1)
            links = []
            async for doc in cursor:
                links.append({
                    "id": str(doc["_id"]),
                    "url": doc["url"],
                    "button_text": doc["button_text"],
                    "row": doc.get("row", 1),
                })
            return links
        except Exception as e:
            logging.error(f"get_fake_links error: {e}")
            return []

    async def remove_fake_link_by_index(self, index: int) -> bool:
        """index is 1-based as shown in /listfakelink."""
        try:
            links = await self.get_fake_links()
            if index < 1 or index > len(links):
                return False
            target = links[index - 1]
            result = await self._c('fake_link_multi').delete_one({
                "url": target["url"],
                "button_text": target["button_text"],
            })
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"remove_fake_link_by_index error: {e}")
            return False

    # ══════════════════════════════════════════
    # PREMIUM SYSTEM  (DreamXBotz se liya)
    # ══════════════════════════════════════════

    async def _b_margin(self) -> int:
        """Temp (verify / ads-free) premium kitne seconds ka ho sakta hai — usse lamba expiry = asli (paid) premium."""
        m = 86400
        try:
            for _id in ("main", "b"):
                d = await self.database['bot_config'].find_one({"_id": _id}) or {}
                m = max(m, int(d.get("verify_premium_seconds", 0) or 0), int(d.get("shortener_free_seconds", 0) or 0))
        except Exception:
            pass
        return m + 60

    async def has_premium_access(self, user_id: int) -> bool:
        """Check karo user ka premium active hai ya nahi.
        B mode mein: sirf asli (paid/admin) premium + B ka apna temp premium (A mode ka temp/free time nahi)."""
        try:
            import datetime
            user = await self.user_data.find_one({"_id": int(user_id)})
            if not user:
                return False
            now = datetime.datetime.now()
            if modectx.cur() == "b":
                eb = user.get("expiry_time_b")
                if isinstance(eb, datetime.datetime) and now <= eb:
                    return True
                ex = user.get("expiry_time")
                return isinstance(ex, datetime.datetime) and (ex - now).total_seconds() > await self._b_margin()
            expiry = user.get("expiry_time")
            if expiry is None:
                return False
            if isinstance(expiry, datetime.datetime) and now <= expiry:
                return True
            # Expire ho gaya — clean karo
            await self.user_data.update_one(
                {"_id": int(user_id)},
                {"$set": {"expiry_time": None}}
            )
            return False
        except Exception as e:
            logging.error(f"has_premium_access error for {user_id}: {e}")
            return False

    async def get_premium_expiry(self, user_id: int):
        """Premium expiry datetime return karo, ya None. (B mode: asli ya B-temp mein se jo lamba ho)"""
        try:
            user = await self.user_data.find_one({"_id": int(user_id)})
            if not user:
                return None
            ex = user.get("expiry_time")
            if modectx.cur() == "b":
                eb = user.get("expiry_time_b")
                vals = [v for v in (ex, eb) if isinstance(v, datetime) ]
                return max(vals) if vals else None
            return ex
        except Exception as e:
            logging.error(f"get_premium_expiry error: {e}")
            return None

    async def add_premium(self, user_id: int, seconds: int, temp: bool = False) -> bool:
        """User ko premium do — seconds mein duration.
        temp=True (verify / ads-free time) aur B mode → sirf B ka temp field; baaki sab (paid, A mode) → expiry_time."""
        import datetime
        try:
            expiry = datetime.datetime.now() + datetime.timedelta(seconds=seconds)
            field = "expiry_time_b" if (temp and modectx.cur() == "b") else "expiry_time"
            await self.user_data.update_one(
                {"_id": int(user_id)},
                {"$set": {field: expiry}},
                upsert=True
            )
            logging.info(f"Premium added for {user_id}, expires {expiry} ({field})")
            return True
        except Exception as e:
            logging.error(f"add_premium error for {user_id}: {e}")
            return False

    async def remove_premium(self, user_id: int) -> bool:
        """User se premium hata do."""
        try:
            result = await self.user_data.update_one(
                {"_id": int(user_id)},
                {"$set": {"expiry_time": None, "expiry_time_b": None}}
            )
            return result.matched_count > 0
        except Exception as e:
            logging.error(f"remove_premium error for {user_id}: {e}")
            return False

    async def get_all_premium_users(self):
        """Sabhi active premium users return karo."""
        import datetime
        try:
            cursor = self.user_data.find(
                {"expiry_time": {"$gt": datetime.datetime.now()}}
            )
            return [doc async for doc in cursor]
        except Exception as e:
            logging.error(f"get_all_premium_users error: {e}")
            return []

    # ══════════════════════════════════════════
    # VERIFY TOKEN SYSTEM
    # Shortener complete hone ke baad user bot
    # link pe aata hai — tab token se verify karke
    # temp premium dete hain + fresh channel link
    # ══════════════════════════════════════════

    async def create_verify_token(self, user_id: int, channel_id: int, token: str, is_request: bool = False, b64: str = "") -> bool:
        """
        Shortener se pehle ek token DB mein save karo.
        Token = random string jo bot deep link mein encode hoga.
        """
        import datetime
        try:
            await self.database['verify_tokens'].update_one(
                {"token": token},
                {"$set": {
                    "token":      token,
                    "user_id":    int(user_id),
                    "channel_id": int(channel_id),
                    "is_request": bool(is_request),
                    "b64":        b64 or "",
                    "created_at": datetime.datetime.now(),
                    "used":       False,
                    "mode":       modectx.cur(),      # B mode token → Mini App / vfy_ B settings se chalega
                }},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"create_verify_token error: {e}")
            return False

    async def set_alt_session(self, token: str, next_url: str = "") -> None:
        """Alternative method shuru: shortener ON ho toh uska URL (/go?r=1 par wapas aata hai), warna khaali."""
        try:
            await self.database['verify_tokens'].update_one(
                {"token": token}, {"$set": {"alt_on": True, "alt_next": next_url or ""}})
        except Exception as e:
            logging.error(f"set_alt_session error: {e}")

    async def update_alt_session(self, token: str, fields: dict) -> None:
        """/go page ke steps ka state (start time, kitne smart links, ads done, shortener time) save karo."""
        try:
            await self.database['verify_tokens'].update_one({"token": token}, {"$set": dict(fields)})
        except Exception as e:
            logging.error(f"update_alt_session error: {e}")

    async def get_alt_cursor(self, user_id: int) -> int:
        """Alternative method ke smart links ka rotating pointer (agla session kaunsa link)."""
        try:
            u = await self._us().find_one({"_id": int(user_id)}, {"alt_cursor": 1})
            return max(0, int((u or {}).get("alt_cursor", 0) or 0))
        except Exception as e:
            logging.error(f"get_alt_cursor error: {e}")
            return 0

    async def set_alt_cursor(self, user_id: int, cursor: int) -> None:
        try:
            await self._us().update_one(
                {"_id": int(user_id)}, {"$set": {"alt_cursor": max(0, int(cursor))}}, upsert=True)
        except Exception as e:
            logging.error(f"set_alt_cursor error: {e}")

    async def get_verify_token(self, token: str) -> dict:
        """Token ka data fetch karo."""
        try:
            doc = await self.database['verify_tokens'].find_one({"token": token})
            return dict(doc) if doc else {}
        except Exception as e:
            logging.error(f"get_verify_token error: {e}")
            return {}

    async def mark_token_used(self, token: str) -> bool:
        """Token use ho gaya — mark karo taaki reuse na ho."""
        try:
            await self.database['verify_tokens'].update_one(
                {"token": token},
                {"$set": {"used": True}}
            )
            return True
        except Exception as e:
            logging.error(f"mark_token_used error: {e}")
            return False

    # ── Mini App (ads) verification helpers ──────────────────────────

    async def claim_verify_token(self, token: str, user_id: int) -> dict:
        """
        Token ko ATOMICALLY claim karo (used=False -> True) taaki ek token
        do baar use na ho sake (double-click / replay safe).
        Sirf wahi user claim kar sakta hai jiske liye token bana tha.
        Claim hua toh doc return, warna {}.
        """
        try:
            doc = await self.database['verify_tokens'].find_one_and_update(
                {"token": token, "used": False, "user_id": int(user_id)},
                {"$set": {"used": True}},
            )
            return dict(doc) if doc else {}
        except Exception as e:
            logging.error(f"claim_verify_token error: {e}")
            return {}

    async def unclaim_verify_token(self, token: str) -> None:
        """Link banane mein error aaya toh token wapas free kar do."""
        try:
            await self.database['verify_tokens'].update_one(
                {"token": token}, {"$set": {"used": False}}
            )
        except Exception as e:
            logging.error(f"unclaim_verify_token error: {e}")

    async def get_ad_cursor(self, user_id: int) -> int:
        """Per-session ads ka rotating pointer (agla session ads list mein kahan se shuru hoga)."""
        try:
            u = await self._us().find_one({"_id": int(user_id)}, {"ad_cursor": 1})
            return max(0, int((u or {}).get("ad_cursor", 0) or 0))
        except Exception as e:
            logging.error(f"get_ad_cursor error: {e}")
            return 0

    async def set_ad_cursor(self, user_id: int, cursor: int) -> None:
        try:
            await self._us().update_one(
                {"_id": int(user_id)}, {"$set": {"ad_cursor": max(0, int(cursor))}}, upsert=True)
        except Exception as e:
            logging.error(f"set_ad_cursor error: {e}")

    async def start_miniapp_session(self, token: str, user_id: int, cursor: int = 0, n: int = 0) -> bool:
        """Mini app khulte hi start time save karo (anti-bypass timing check) + is session ke ads ka cursor/count."""
        import datetime
        try:
            await self.database['verify_tokens'].update_one(
                {"token": token, "user_id": int(user_id)},
                {"$set": {"mini_started_at": datetime.datetime.now(), "mini_cursor": int(cursor), "mini_n": int(n)}},
            )
            return True
        except Exception as e:
            logging.error(f"start_miniapp_session error: {e}")
            return False

    async def set_token_prompt(self, token: str, chat_id: int, msg_id: int) -> None:
        """'Watch Video Ad' wale message ka ID save karo — link milte hi delete hoga."""
        try:
            await self.database['verify_tokens'].update_one(
                {"token": token},
                {"$set": {"prompt_chat_id": int(chat_id), "prompt_msg_id": int(msg_id)}},
            )
        except Exception as e:
            logging.error(f"set_token_prompt error: {e}")

    # ── Mini App daily progress + stats (IST din ke hisaab se) ───────

    @staticmethod
    def _ist_date() -> str:
        import datetime
        return (datetime.datetime.utcnow() + datetime.timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")

    async def add_miniapp_progress(self, user_id: int, shown: int) -> int:
        """Aaj ke liye user ka ads-count badhao. Naya total return karta hai."""
        try:
            from pymongo import ReturnDocument
            date = self._ist_date()
            doc = await self._c('miniapp_daily').find_one_and_update(
                {"_id": f"{int(user_id)}:{date}"},
                {"$inc": {"count": int(shown), "sessions": 1},
                 "$set": {"uid": int(user_id), "date": date}},
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
            await self._c('miniapp_stats').update_one(
                {"_id": date},
                {"$inc": {"sessions": 1, "ads": int(shown)}},
                upsert=True,
            )
            return int(doc.get("count", shown))
        except Exception as e:
            logging.error(f"add_miniapp_progress error: {e}")
            return int(shown)

    async def get_miniapp_daily_count(self, user_id: int) -> int:
        try:
            doc = await self._c('miniapp_daily').find_one(
                {"_id": f"{int(user_id)}:{self._ist_date()}"}
            )
            return int(doc.get("count", 0)) if doc else 0
        except Exception as e:
            logging.error(f"get_miniapp_daily_count error: {e}")
            return 0

    async def get_miniapp_stats(self) -> dict:
        """Admin panel ke liye: aaj + total sessions/ads + aaj ke unique users."""
        try:
            date = self._ist_date()
            today = await self._c('miniapp_stats').find_one({"_id": date}) or {}
            users_today = await self._c('miniapp_daily').count_documents({"date": date})
            tot_sessions = tot_ads = 0
            async for d in self._c('miniapp_stats').find({}):
                tot_sessions += int(d.get("sessions", 0))
                tot_ads += int(d.get("ads", 0))
            return {
                "today_sessions": int(today.get("sessions", 0)),
                "today_ads": int(today.get("ads", 0)),
                "users_today": int(users_today),
                "total_sessions": tot_sessions,
                "total_ads": tot_ads,
            }
        except Exception as e:
            logging.error(f"get_miniapp_stats error: {e}")
            return {"today_sessions": 0, "today_ads": 0, "users_today": 0, "total_sessions": 0, "total_ads": 0}

    # ── FSub extras (Sufistobot se port): layout, text/photo, auto-remove, limits, rotation ──

    async def get_fsub_layout(self) -> int:
        """1 = ek row mein 1 button (default), 2 = ek row mein 2 buttons."""
        try:
            doc = await self._c('bot_settings').find_one({"_id": "fsub_layout"})
            return 2 if doc and int(doc.get("per_row", 1)) == 2 else 1
        except Exception as e:
            logging.error(f"get_fsub_layout error: {e}")
            return 1

    async def set_fsub_layout(self, per_row: int) -> bool:
        try:
            await self._c('bot_settings').update_one(
                {"_id": "fsub_layout"},
                {"$set": {"per_row": 2 if int(per_row) == 2 else 1}},
                upsert=True,
            )
            return True
        except Exception as e:
            logging.error(f"set_fsub_layout error: {e}")
            return False

    async def get_fsub_ui(self) -> dict:
        """Custom fsub text + photo. text="" -> default text. pic="" -> default FSUB_PIC, "none" -> sirf text."""
        try:
            doc = await self._c('bot_settings').find_one({"_id": "fsub_ui"}) or {}
            return {"text": doc.get("text", "") or "", "pic": doc.get("pic", "") or ""}
        except Exception as e:
            logging.error(f"get_fsub_ui error: {e}")
            return {"text": "", "pic": ""}

    async def set_fsub_ui(self, **fields) -> bool:
        try:
            await self._c('bot_settings').update_one(
                {"_id": "fsub_ui"}, {"$set": fields}, upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"set_fsub_ui error: {e}")
            return False

    async def get_fsub_doc(self, channel_id: int):
        return await self.fsub_data.find_one({"channel_id": channel_id})

    async def get_all_fsub_docs(self) -> list:
        try:
            return await self.fsub_data.find({"status": "active"}).sort("created_at", 1).to_list(None)
        except Exception as e:
            logging.error(f"get_all_fsub_docs error: {e}")
            return []

    async def set_fsub_remove_at(self, channel_id: int, when) -> bool:
        """Channel ko fsub se auto remove karne ka time (naive UTC datetime). None = clear."""
        if when:
            res = await self.fsub_data.update_one({"channel_id": channel_id}, {"$set": {"remove_at": when}})
        else:
            res = await self.fsub_data.update_one({"channel_id": channel_id}, {"$unset": {"remove_at": ""}})
        return res.matched_count > 0

    async def set_fsub_request_limit(self, channel_id: int, limit: int, base_real=None) -> bool:
        """Ab se `limit` NAYE requests (request mode) / joins (normal mode) aate hi channel auto remove. 0 = clear.
        base_real = Telegram invite-link ke REAL numbers ka abhi ka total (counting yahin se shuru)."""
        doc = await self.fsub_data.find_one({"channel_id": channel_id})
        if not doc:
            return False
        if limit and limit > 0:
            fields = {
                "request_limit": int(limit),
                "limit_base_req": doc.get("request_count", 0),
                "limit_base_join": doc.get("join_count", 0),
                "limit_carry": 0,
            }
            if base_real is not None:
                fields["limit_base_real"] = int(base_real)
            await self.fsub_data.update_one({"channel_id": channel_id}, {"$set": fields})
            if base_real is None:
                await self.fsub_data.update_one({"channel_id": channel_id}, {"$unset": {"limit_base_real": ""}})
        else:
            await self.fsub_data.update_one({"channel_id": channel_id}, {"$unset": {
                "request_limit": "", "limit_base_req": "", "limit_base_join": "",
                "limit_base_real": "", "limit_carry": "",
            }})
        return True

    async def set_fsub_limit_carry(self, channel_id: int, carry: int) -> None:
        """Link rotate hone par progress yaad rakho (naya link 0 se shuru hota hai)."""
        await self.fsub_data.update_one(
            {"channel_id": channel_id},
            {"$set": {"limit_carry": int(carry), "limit_base_real": 0}},
        )

    async def set_fsub_link_rotation(self, channel_id: int, hours: int) -> bool:
        """Har `hours` ghante mein purana invite link expire + naya link. 0 = off."""
        if hours and hours > 0:
            res = await self.fsub_data.update_one({"channel_id": channel_id}, {"$set": {
                "rotate_hours": int(hours), "rotate_since": datetime.utcnow(),
            }})
        else:
            res = await self.fsub_data.update_one({"channel_id": channel_id}, {"$unset": {
                "rotate_hours": "", "rotate_since": "",
            }})
        return res.matched_count > 0

    async def mark_fsub_rotated(self, channel_id: int) -> None:
        await self.fsub_data.update_one({"channel_id": channel_id}, {"$set": {"rotate_since": datetime.utcnow()}})

    # ── Ads-free (Mini App daily goal reward): sirf ads hatate hain, FSub PHIR BHI lagta hai ──

    async def set_ads_free(self, user_id: int, seconds: int) -> None:
        """Ads-free time badhao (kabhi kam nahi karta)."""
        if seconds <= 0:
            return
        try:
            target = datetime.now() + timedelta(seconds=int(seconds))
            user = await self._us().find_one({"_id": int(user_id)}) or {}
            cur = user.get("ads_free_until")
            if isinstance(cur, datetime) and cur >= target:
                return
            await self._us().update_one(
                {"_id": int(user_id)}, {"$set": {"ads_free_until": target}}, upsert=True
            )
        except Exception as e:
            logging.error(f"set_ads_free error: {e}")

    async def has_ads_free(self, user_id: int) -> bool:
        try:
            user = await self._us().find_one({"_id": int(user_id)})
            until = user.get("ads_free_until") if user else None
            return isinstance(until, datetime) and datetime.now() <= until
        except Exception as e:
            logging.error(f"has_ads_free error: {e}")
            return False

    async def reset_miniapp_progress(self, user_id: int) -> None:
        """Goal poora hone ke baad aaj ka ads-count 0 karo (naya cycle)."""
        try:
            await self._c('miniapp_daily').update_one(
                {"_id": f"{int(user_id)}:{self._ist_date()}"}, {"$set": {"count": 0}}
            )
        except Exception as e:
            logging.error(f"reset_miniapp_progress error: {e}")

    # ── Link flow "Custom": user ab sequence ke kaunse step par hai (0 = pehla open) ──

    async def get_link_pos(self, user_id: int) -> int:
        try:
            u = await self._us().find_one({"_id": int(user_id)}, {"link_pos": 1})
            return max(0, int((u or {}).get("link_pos", 0) or 0))
        except Exception as e:
            logging.error(f"get_link_pos error: {e}")
            return 0

    async def set_link_pos(self, user_id: int, pos: int) -> None:
        try:
            await self._us().update_one(
                {"_id": int(user_id)}, {"$set": {"link_pos": max(0, int(pos))}}, upsert=True)
        except Exception as e:
            logging.error(f"set_link_pos error: {e}")

    # ── Link flow "FSub pehle, phir Ads": user ne FSub screen dekhi thi -> wapas aane par seedha link ──

    async def set_fsub_pending(self, user_id: int) -> None:
        try:
            await self._us().update_one(
                {"_id": int(user_id)}, {"$set": {"fsub_pending": datetime.now()}}, upsert=True)
        except Exception as e:
            logging.error(f"set_fsub_pending error: {e}")

    async def pop_fsub_pending(self, user_id: int) -> bool:
        """True agar user ne pichle 24h mein FSub screen dekhi thi (flag hata deta hai)."""
        try:
            doc = await self._us().find_one_and_update(
                {"_id": int(user_id), "fsub_pending": {"$exists": True}}, {"$unset": {"fsub_pending": ""}})
            at = doc.get("fsub_pending") if doc else None
            return isinstance(at, datetime) and (datetime.now() - at) < timedelta(hours=24)
        except Exception as e:
            logging.error(f"pop_fsub_pending error: {e}")
            return False

    # ── Link flow ke beech ke messages (FSub screen, welcome...) — link aate hi delete karne ke liye ──

    async def push_flow_msg(self, user_id: int, chat_id: int, msg_id: int) -> None:
        try:
            await self.user_data.update_one(
                {"_id": int(user_id)},
                {"$push": {"flow_msgs": {"$each": [[int(chat_id), int(msg_id)]], "$slice": -8}}},
                upsert=True)
        except Exception as e:
            logging.error(f"push_flow_msg error: {e}")

    async def pop_flow_msgs(self, user_id: int) -> list:
        try:
            doc = await self.user_data.find_one_and_update(
                {"_id": int(user_id), "flow_msgs": {"$exists": True}}, {"$unset": {"flow_msgs": ""}})
            return list(doc.get("flow_msgs", [])) if doc else []
        except Exception as e:
            logging.error(f"pop_flow_msgs error: {e}")
            return []

    # ── Ad fallback: ads fail hone par FSub se link (din mein limited baar) ──

    async def fallback_use(self, user_id: int, limit: int) -> bool:
        """Aaj ke quota se 1 use karo. False agar limit khatam."""
        try:
            uid, today = int(user_id), self._ist_date()
            await self._us().update_one({"_id": uid}, {"$setOnInsert": {"fb_count": 0, "fb_day": ""}}, upsert=True)
            await self._us().update_one({"_id": uid, "fb_day": {"$ne": today}}, {"$set": {"fb_day": today, "fb_count": 0}})
            r = await self._us().update_one({"_id": uid, "fb_count": {"$lt": int(limit)}}, {"$inc": {"fb_count": 1}})
            return r.modified_count > 0
        except Exception as e:
            logging.error(f"fallback_use error: {e}")
            return False

    async def set_ads_bypass(self, user_id: int, seconds: int = 1800) -> None:
        try:
            await self._us().update_one(
                {"_id": int(user_id)},
                {"$set": {"ads_bypass_until": datetime.now() + timedelta(seconds=int(seconds))}}, upsert=True)
        except Exception as e:
            logging.error(f"set_ads_bypass error: {e}")

    async def has_ads_bypass(self, user_id: int) -> bool:
        try:
            u = await self._us().find_one({"_id": int(user_id)})
            until = u.get("ads_bypass_until") if u else None
            return isinstance(until, datetime) and datetime.now() <= until
        except Exception as e:
            logging.error(f"has_ads_bypass error: {e}")
            return False

    async def pop_ads_bypass(self, user_id: int) -> None:
        try:
            await self._us().update_one({"_id": int(user_id)}, {"$unset": {"ads_bypass_until": ""}})
        except Exception as e:
            logging.error(f"pop_ads_bypass error: {e}")

    async def delete_old_tokens(self) -> None:
        """1 ghante se purane tokens delete karo (cleanup)."""
        import datetime
        try:
            cutoff = datetime.datetime.now() - datetime.timedelta(hours=1)
            await self.database['verify_tokens'].delete_many(
                {"created_at": {"$lt": cutoff}}
            )
        except Exception as e:
            logging.error(f"delete_old_tokens error: {e}")

    # ══════════════════════════════════════════
    # CHANNEL ALIAS METHODS
    # Purana channel ban ho → naye channel pe redirect
    # ══════════════════════════════════════════

    async def set_channel_alias(self, old_channel_id: int, new_channel_id: int) -> bool:
        """
        Purane channel ka link naye channel pe point karo.
        Jab bhi koi old channel ID ka link use karega, new channel ka invite milega.
        """
        try:
            await self.database['channel_aliases'].update_one(
                {"old_channel_id": old_channel_id},
                {"$set": {
                    "old_channel_id": old_channel_id,
                    "new_channel_id": new_channel_id,
                    "created_at": datetime.utcnow()
                }},
                upsert=True
            )
            logging.info(f"Alias set: {old_channel_id} → {new_channel_id}")
            return True
        except Exception as e:
            logging.error(f"set_channel_alias error: {e}")
            return False

    async def get_channel_alias(self, channel_id: int) -> Optional[int]:
        """
        Agar channel ka alias set hai to naya channel ID return karo, warna None.
        """
        try:
            doc = await self.database['channel_aliases'].find_one({"old_channel_id": channel_id})
            return doc["new_channel_id"] if doc else None
        except Exception as e:
            logging.error(f"get_channel_alias error: {e}")
            return None

    async def remove_channel_alias(self, old_channel_id: int) -> bool:
        """Alias remove karo."""
        try:
            result = await self.database['channel_aliases'].delete_one({"old_channel_id": old_channel_id})
            return result.deleted_count > 0
        except Exception as e:
            logging.error(f"remove_channel_alias error: {e}")
            return False

    async def list_channel_aliases(self) -> list:
        """Saare aliases list karo."""
        try:
            docs = await self.database['channel_aliases'].find({}).to_list(None)
            return docs if docs else []
        except Exception as e:
            logging.error(f"list_channel_aliases error: {e}")
            return []

    # ══════════════════════════════════════════
    # REQUEST NOTIFICATION - User ka pending link store karo
    # Jab approve ho toh usse wahi link bhejo
    # ══════════════════════════════════════════

    async def save_user_request_link(
        self,
        user_id: int,
        channel_id: int,
        req_encoded: str,
        link_msg_id: int = None,
        link_chat_id: int = None,
        invite_link: str = None
    ) -> bool:
        """
        Jab user request link click kare, uska pending data save karo.
        invite_link  = wahi join link jo user ko diya tha (approve pe button mein aayega)
        link_msg_id  = bot ka 'HERE IS YOUR LINK' message ID (approve pe delete hoga)
        link_chat_id = us message ka chat_id
        """
        try:
            data = {
                "user_id": user_id,
                "channel_id": channel_id,
                "req_encoded": req_encoded,
                "created_at": datetime.utcnow()
            }
            if link_msg_id is not None:
                data["link_msg_id"] = link_msg_id
            if link_chat_id is not None:
                data["link_chat_id"] = link_chat_id
            if invite_link is not None:
                data["invite_link"] = invite_link

            await self.database['user_request_links'].update_one(
                {"user_id": user_id, "channel_id": channel_id},
                {"$set": data},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"save_user_request_link error: {e}")
            return False

    async def get_user_request_doc(self, user_id: int, channel_id: int) -> Optional[dict]:
        """Full document fetch karo — req_encoded + link_msg_id + link_chat_id."""
        try:
            doc = await self.database['user_request_links'].find_one(
                {"user_id": user_id, "channel_id": channel_id}
            )
            return dict(doc) if doc else None
        except Exception as e:
            logging.error(f"get_user_request_doc error: {e}")
            return None
        """User ka stored request encoded link fetch karo."""
        try:
            doc = await self.database['user_request_links'].find_one(
                {"user_id": user_id, "channel_id": channel_id}
            )
            return doc["req_encoded"] if doc else None
        except Exception as e:
            logging.error(f"get_user_request_link error: {e}")
            return None

    async def delete_user_request_link(self, user_id: int, channel_id: int) -> bool:
        """Notify ke baad link delete karo (cleanup)."""
        try:
            await self.database['user_request_links'].delete_one(
                {"user_id": user_id, "channel_id": channel_id}
            )
            return True
        except Exception as e:
            logging.error(f"delete_user_request_link error: {e}")
            return False


    # ══════════════════════════════════════════
    # TUTORIAL SYSTEM
    # FSub aur LinkShortener ke liye tutorial video
    # ══════════════════════════════════════════

    async def set_tutorial(self, tutorial_type: str, file_id: str) -> bool:
        """
        Tutorial video set karo.
        tutorial_type: 'fsub' ya 'linkshortner'
        file_id: Telegram video file_id
        """
        try:
            await self._c('tutorial_config').update_one(
                {"_id": tutorial_type},
                {"$set": {
                    "_id": tutorial_type,
                    "file_id": file_id,
                    "enabled": True,
                    "updated_at": datetime.utcnow()
                }},
                upsert=True
            )
            logging.info(f"Tutorial set: type={tutorial_type}, file_id={file_id[:20]}...")
            return True
        except Exception as e:
            logging.error(f"set_tutorial error: {e}")
            return False

    async def get_tutorial(self, tutorial_type: str) -> Optional[dict]:
        """Tutorial config fetch karo. None if not set or disabled."""
        try:
            doc = await self._c('tutorial_config').find_one({"_id": tutorial_type})
            if doc and doc.get("enabled", False):
                return {"file_id": doc["file_id"]}
            return None
        except Exception as e:
            logging.error(f"get_tutorial error: {e}")
            return None

    async def toggle_tutorial(self, tutorial_type: str, enabled: bool) -> bool:
        """Tutorial on/off karo."""
        try:
            result = await self._c('tutorial_config').update_one(
                {"_id": tutorial_type},
                {"$set": {"enabled": enabled, "updated_at": datetime.utcnow()}}
            )
            return result.matched_count > 0
        except Exception as e:
            logging.error(f"toggle_tutorial error: {e}")
            return False

    async def get_tutorial_status(self, tutorial_type: str) -> dict:
        """Tutorial ka full status return karo."""
        try:
            doc = await self._c('tutorial_config').find_one({"_id": tutorial_type})
            if not doc:
                return {"exists": False, "enabled": False, "file_id": None}
            return {
                "exists": True,
                "enabled": doc.get("enabled", False),
                "file_id": doc.get("file_id")
            }
        except Exception as e:
            logging.error(f"get_tutorial_status error: {e}")
            return {"exists": False, "enabled": False, "file_id": None}

    async def get_auto_accept(self) -> bool:
        """
        Auto Request Accept setting fetch karo (normal channels ke liye,
        jahan bot admin hai). Default True (ON) — yeh purana/existing
        behaviour hai, isliye off tabhi hoga jab explicitly off kiya jaye.
        """
        try:
            doc = await self.database['bot_settings'].find_one({"_id": "auto_request_accept"})
            if doc is None:
                return True
            return doc.get("enabled", True)
        except Exception as e:
            logging.error(f"get_auto_accept error: {e}")
            return True

    async def set_auto_accept(self, enabled: bool) -> bool:
        """Auto Request Accept ON/OFF set karo."""
        try:
            await self.database['bot_settings'].update_one(
                {"_id": "auto_request_accept"},
                {"$set": {"enabled": enabled, "updated_at": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"set_auto_accept error: {e}")
            return False

    # ============================================
    # SMART FSUB AUTO-CHECK
    # OFF (default) -> bilkul purana behaviour: user ko khud "• Joined •"
    #                   button click karna padta hai.
    # ON            -> user ke baaki channels join karte hi (background
    #                   poll ke zariye detect hoke) link automatically
    #                   bhej diya jaata hai, click ki zaroorat nahi.
    # ============================================
    async def get_auto_check(self) -> bool:
        """FSub smart auto-check ON hai ya OFF (default: OFF, purana behaviour)."""
        try:
            doc = await self._c('bot_settings').find_one({"_id": "fsub_auto_check"})
            return bool(doc.get("enabled", False)) if doc else False
        except Exception as e:
            logging.error(f"get_auto_check error: {e}")
            return False

    async def set_auto_check(self, enabled: bool) -> bool:
        """FSub smart auto-check ON/OFF set karo."""
        try:
            await self._c('bot_settings').update_one(
                {"_id": "fsub_auto_check"},
                {"$set": {"enabled": enabled, "updated_at": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"set_auto_check error: {e}")
            return False

    # ============================================
    # ADMIN CHANNELS (Fban/Funban/Gbroadcast/Gdescription ke liye)
    # "channel_data" (link-share channels) + "fsub_data" (FSub channels)
    # dono jagah bot admin hota hai — dono ko union+dedupe karke
    # ek combined list return karta hai.
    # ============================================
    async def get_admin_channels(self) -> List[int]:
        """Un sab channels ki list jaha bot admin hai (link-share + FSub, duplicate hataakar)."""
        try:
            link_channels = await self.get_channels()
            fsub_channels = await self.get_fsub_channels()
            combined = list(dict.fromkeys(list(link_channels) + list(fsub_channels)))
            return combined
        except Exception as e:
            logging.error(f"Error fetching admin channels: {e}")
            return []

    async def save_last_broadcast(self, entries: list) -> bool:
        """Sabse latest /gbroadcast ke (channel_id, message_id) pairs save karo,
        taaki /cbroadcast baad mein unhe delete kar sake. Har naye /gbroadcast pe overwrite hota hai."""
        try:
            await self.broadcast_data.update_one(
                {"_id": "last_broadcast"},
                {"$set": {"entries": entries, "created_at": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"Error saving last broadcast: {e}")
            return False

    async def get_last_broadcast(self) -> Optional[dict]:
        """Sabse latest /gbroadcast ka record laao (entries list ke saath)."""
        try:
            return await self.broadcast_data.find_one({"_id": "last_broadcast"})
        except Exception as e:
            logging.error(f"Error fetching last broadcast: {e}")
            return None

    async def clear_last_broadcast(self) -> bool:
        """/cbroadcast ke baad record clear kar do taaki dobara /cbroadcast chalane pe kuch delete na ho."""
        try:
            await self.broadcast_data.delete_one({"_id": "last_broadcast"})
            return True
        except Exception as e:
            logging.error(f"Error clearing last broadcast: {e}")
            return False

    # ============================================
    # FSUB CHECK DURATION (cooldown)
    # OFF (default)      -> har baar poora FSub check hota hai, bilkul pehle jaisa.
    # ON + duration set  -> ek baar user ka FSub check pass (verified) hone ke
    #                       baad, us duration (12h/24h/48h/7d) ke andar agar
    #                       koi NAYA FSub channel bhi add ho jaaye, us user ko
    #                       dubara check/join karne ki zarurat nahi — turant
    #                       access mil jaata hai. Duration khatam hone ke baad
    #                       normal check phir se lagne lagta hai.
    # ============================================
    async def get_fsub_check_duration(self) -> dict:
        """{"enabled": bool, "hours": int} return karta hai. Default: OFF."""
        try:
            doc = await self._c('bot_settings').find_one({"_id": "fsub_check_duration"})
            if not doc:
                return {"enabled": False, "hours": 0}
            return {"enabled": bool(doc.get("enabled", False)), "hours": int(doc.get("hours", 0) or 0)}
        except Exception as e:
            logging.error(f"get_fsub_check_duration error: {e}")
            return {"enabled": False, "hours": 0}

    async def set_fsub_check_duration(self, enabled: bool, hours: int = 0) -> bool:
        """FSub check-duration (cooldown) ON/OFF + duration (hours mein) set karo."""
        try:
            await self._c('bot_settings').update_one(
                {"_id": "fsub_check_duration"},
                {"$set": {"enabled": enabled, "hours": hours, "updated_at": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"set_fsub_check_duration error: {e}")
            return False

    async def set_fsub_verified(self, user_id: int) -> bool:
        """User ka FSub check abhi-abhi pass hua — timestamp save karo (cooldown ke liye)."""
        try:
            await self._us().update_one(
                {"_id": int(user_id)},
                {"$set": {"fsub_verified_at": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"set_fsub_verified error: {e}")
            return False

    async def get_fsub_verified_at(self, user_id: int):
        """User ka last FSub-pass timestamp laao (ya None agar kabhi verify nahi hua)."""
        try:
            user = await self._us().find_one({"_id": int(user_id)})
            return user.get("fsub_verified_at") if user else None
        except Exception as e:
            logging.error(f"get_fsub_verified_at error: {e}")
            return None

    async def get_community(self) -> dict:
        """
        Community info (name/username/link) fetch karo — /community
        command se set kiya hua. Kuch set nahi hai toh config.py wale
        DEFAULT_COMMUNITY_* defaults return honge.
        """
        try:
            doc = await self.database['bot_settings'].find_one({"_id": "community"})
            if not doc:
                return {
                    "name": DEFAULT_COMMUNITY_NAME,
                    "username": DEFAULT_COMMUNITY_USERNAME,
                    "link": DEFAULT_COMMUNITY_LINK
                }
            return {
                "name": doc.get("name", DEFAULT_COMMUNITY_NAME),
                "username": doc.get("username", DEFAULT_COMMUNITY_USERNAME),
                "link": doc.get("link", DEFAULT_COMMUNITY_LINK)
            }
        except Exception as e:
            logging.error(f"get_community error: {e}")
            return {
                "name": DEFAULT_COMMUNITY_NAME,
                "username": DEFAULT_COMMUNITY_USERNAME,
                "link": DEFAULT_COMMUNITY_LINK
            }

    async def set_community(self, name: str, username: str, link: str) -> bool:
        """Community naam/username/link set karo (/community command se)."""
        try:
            await self.database['bot_settings'].update_one(
                {"_id": "community"},
                {"$set": {"name": name, "username": username, "link": link, "updated_at": datetime.utcnow()}},
                upsert=True
            )
            return True
        except Exception as e:
            logging.error(f"set_community error: {e}")
            return False

Seishiro = Master(DB_URL, DB_NAME)
