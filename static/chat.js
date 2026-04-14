(function () {
    function createNode(tagName, className, textContent) {
        var node = document.createElement(tagName);
        if (className) {
            node.className = className;
        }
        if (typeof textContent === "string") {
            node.textContent = textContent;
        }
        return node;
    }

    function getInitials(value, fallback) {
        var words = String(value || "").trim().split(/\s+/).filter(Boolean);
        if (!words.length) {
            return fallback || "?";
        }
        if (words.length === 1) {
            return words[0].slice(0, 2).toUpperCase();
        }
        return (words[0][0] + words[1][0]).toUpperCase();
    }

    function applyAvatarFace(node, avatarUrl, fallbackText) {
        var fallbackNode = createNode("span", "chat-avatar-fallback", fallbackText || "?");
        if (avatarUrl) {
            var imageNode = createNode("img", "chat-avatar-image");
            imageNode.src = avatarUrl;
            imageNode.alt = "";
            imageNode.loading = "lazy";
            node.appendChild(imageNode);
            node.classList.add("has-image");
        } else {
            node.classList.remove("has-image");
        }
        node.appendChild(fallbackNode);
        return fallbackNode;
    }

    function getChannelBadge(target) {
        var match = String(target || "").match(/channel:(\d+)/);
        return match ? match[1] : "#";
    }

    function buildHandle(username) {
        var cleanUsername = String(username || "").trim();
        return cleanUsername ? "@" + cleanUsername : "";
    }

    function joinBits(values) {
        return values.filter(Boolean).join(" | ");
    }

    function normalizeSearch(value) {
        return String(value || "").trim().toLowerCase();
    }

    function normalizeThreadDescription(value) {
        var text = String(value || "").trim();
        if (!text) {
            return "";
        }
        if (/^edited$/i.test(text)) {
            return "";
        }
        return text;
    }

    function parseTimestamp(value) {
        var match = String(value || "").match(
            /^(\d{4})-(\d{2})-(\d{2})(?:\s+(\d{2}):(\d{2})(?::(\d{2}))?)?$/
        );
        if (!match) {
            return null;
        }
        return new Date(
            Number(match[1]),
            Number(match[2]) - 1,
            Number(match[3]),
            Number(match[4] || 0),
            Number(match[5] || 0),
            Number(match[6] || 0)
        );
    }

    function isSameCalendarDay(left, right) {
        return !!(
            left &&
            right &&
            left.getFullYear() === right.getFullYear() &&
            left.getMonth() === right.getMonth() &&
            left.getDate() === right.getDate()
        );
    }

    function formatTimeOnly(value) {
        var date = parseTimestamp(value);
        if (!date) {
            return value || "";
        }
        return date.toLocaleTimeString(undefined, {
            hour: "numeric",
            minute: "2-digit"
        });
    }

    function getDateKey(value) {
        var match = String(value || "").match(/^(\d{4}-\d{2}-\d{2})/);
        return match ? match[1] : "";
    }

    function formatDateDivider(value) {
        var date = parseTimestamp(value);
        if (!date) {
            return "Messages";
        }

        var today = new Date();
        today.setHours(0, 0, 0, 0);
        var yesterday = new Date(today);
        yesterday.setDate(today.getDate() - 1);
        var compare = new Date(date.getFullYear(), date.getMonth(), date.getDate());

        if (compare.getTime() === today.getTime()) {
            return "Today";
        }
        if (compare.getTime() === yesterday.getTime()) {
            return "Yesterday";
        }

        return date.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric"
        });
    }

    function formatConversationTime(value) {
        var date = parseTimestamp(value);
        if (!date) {
            return "";
        }

        var now = new Date();
        var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        var yesterday = new Date(today);
        yesterday.setDate(today.getDate() - 1);
        var compare = new Date(date.getFullYear(), date.getMonth(), date.getDate());

        if (compare.getTime() === today.getTime()) {
            return formatTimeOnly(value);
        }
        if (compare.getTime() === yesterday.getTime()) {
            return "Yesterday";
        }
        if (date.getFullYear() === now.getFullYear()) {
            return date.toLocaleDateString(undefined, {
                month: "short",
                day: "numeric"
            });
        }
        return date.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric",
            year: "numeric"
        });
    }

    function formatLastActivity(value) {
        var date = parseTimestamp(value);
        if (!date) {
            return "";
        }

        var now = new Date();
        var diffMinutes = Math.max(0, Math.round((now.getTime() - date.getTime()) / 60000));

        if (diffMinutes < 1) {
            return "Just now";
        }
        if (diffMinutes < 60) {
            return diffMinutes + "m ago";
        }
        if (diffMinutes < 24 * 60 && isSameCalendarDay(now, date)) {
            return "Today at " + formatTimeOnly(value);
        }

        var yesterday = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        yesterday.setDate(yesterday.getDate() - 1);
        if (isSameCalendarDay(yesterday, date)) {
            return "Yesterday at " + formatTimeOnly(value);
        }

        return date.toLocaleDateString(undefined, {
            month: "short",
            day: "numeric"
        }) + " at " + formatTimeOnly(value);
    }

    function formatSyncLabel(syncState, lastSyncAt) {
        if (syncState === "syncing") {
            return "Syncing...";
        }
        if (syncState === "error") {
            return "Sync issue";
        }
        if (!lastSyncAt) {
            return "Waiting for sync";
        }

        var diffSeconds = Math.max(0, Math.round((Date.now() - lastSyncAt) / 1000));
        if (diffSeconds < 8) {
            return "Updated just now";
        }
        if (diffSeconds < 60) {
            return "Updated " + diffSeconds + "s ago";
        }

        var diffMinutes = Math.round(diffSeconds / 60);
        if (diffMinutes < 60) {
            return "Updated " + diffMinutes + "m ago";
        }

        return "Updated at " + new Date(lastSyncAt).toLocaleTimeString(undefined, {
            hour: "numeric",
            minute: "2-digit"
        });
    }

    function canGroupMessages(previousMessage, nextMessage) {
        if (!previousMessage || !nextMessage) {
            return false;
        }
        if (String(previousMessage.sender_username || "").toLowerCase() !== String(nextMessage.sender_username || "").toLowerCase()) {
            return false;
        }

        var previousDate = parseTimestamp(previousMessage.created_at);
        var nextDate = parseTimestamp(nextMessage.created_at);
        if (!previousDate || !nextDate || !isSameCalendarDay(previousDate, nextDate)) {
            return false;
        }

        return Math.abs(nextDate.getTime() - previousDate.getTime()) <= 5 * 60 * 1000;
    }

    function mergeMessages(existingMessages, incomingMessages) {
        var map = {};
        (existingMessages || []).forEach(function (message) {
            map[message.id] = message;
        });
        (incomingMessages || []).forEach(function (message) {
            map[message.id] = message;
        });

        return Object.keys(map).map(function (id) {
            return map[id];
        }).sort(function (left, right) {
            return Number(left.id) - Number(right.id);
        });
    }

    function initChatWidget(root) {
        if (!root || root.dataset.bound === "true") {
            return;
        }
        root.dataset.bound = "true";

        var mobileQuery = window.matchMedia("(max-width: 860px)");
        var maxAttachmentSizeBytes = 15 * 1024 * 1024;
        var state = {
            chatOpen: false,
            currentView: "list",
            overview: null,
            activeType: "",
            activeTarget: "",
            activeThread: null,
            threadMessages: [],
            threadMeta: null,
            loadingOlder: false,
            searchTerm: "",
            filterMode: "people",
            drafts: {},
            collapsedSidebarForChat: false,
            syncState: "idle",
            lastSyncAt: 0,
            sending: false,
            settingsOpen: false,
            unseenCount: 0,
            pollHandle: 0,
            hasBootstrappedOverview: false,
            overviewThreadSnapshot: {},
            liveNotifications: {}
        };

        var refs = {
            chatTrigger: root.querySelector("[data-chat-trigger]"),
            chatBadge: root.querySelector("[data-chat-badge]"),
            chatPanel: root.querySelector("[data-chat-panel]"),
            browser: root.querySelector("[data-chat-browser]"),
            threadPanel: root.querySelector("[data-chat-thread-panel]"),
            chatSummary: root.querySelector("[data-chat-summary]"),
            chatStatUnread: root.querySelector("[data-chat-stat-unread]"),
            chatStatOnline: root.querySelector("[data-chat-stat-online]"),
            syncStatus: root.querySelector("[data-chat-sync-status]"),
            chatSearch: root.querySelector("[data-chat-search]"),
            filterButtons: Array.prototype.slice.call(root.querySelectorAll("[data-chat-filter]")),
            unifiedList: root.querySelector('[data-chat-list="unified"]'),
            back: root.querySelector("[data-chat-back]"),
            threadAvatar: root.querySelector("[data-chat-thread-avatar]"),
            threadAvatarImage: root.querySelector("[data-chat-thread-avatar-image]"),
            threadAvatarText: root.querySelector("[data-chat-thread-avatar-text]"),
            threadAvatarStatus: root.querySelector("[data-chat-thread-avatar-status]"),
            title: root.querySelector("[data-chat-thread-title]"),
            subtitle: root.querySelector("[data-chat-thread-subtitle]"),
            refresh: root.querySelector("[data-chat-refresh]"),
            editToggle: root.querySelector("[data-chat-edit-toggle]"),
            channelForm: root.querySelector("[data-chat-channel-form]"),
            channelRoomKey: root.querySelector("[data-chat-channel-room-key]"),
            channelTitleInput: root.querySelector("[data-chat-channel-title-input]"),
            channelDescriptionInput: root.querySelector("[data-chat-channel-description-input]"),
            editCancel: root.querySelector("[data-chat-edit-cancel]"),
            threadTools: root.querySelector("[data-chat-thread-tools]"),
            loadOlder: root.querySelector("[data-chat-load-older]"),
            jumpLatest: root.querySelector("[data-chat-jump-latest]"),
            feed: root.querySelector("[data-chat-messages]"),
            compose: root.querySelector("[data-chat-compose]"),
            composeType: root.querySelector("[data-chat-compose-type]"),
            composeTarget: root.querySelector("[data-chat-compose-target]"),
            composeInput: root.querySelector("[data-chat-compose-input]"),
            fileInput: root.querySelector("[data-chat-file-input]"),
            fileTrigger: root.querySelector("[data-chat-file-trigger]"),
            fileName: root.querySelector("[data-chat-file-name]"),
            filePreview: root.querySelector("[data-chat-file-preview]"),
            fileChip: root.querySelector("[data-chat-file-chip]"),
            fileClear: root.querySelector("[data-chat-file-clear]"),
            sendButton: root.querySelector(".chat-send-btn"),
            composeStatus: root.querySelector("[data-chat-compose-status]")
        };

        function fetchJson(url, options) {
            var requestOptions = options || {};
            requestOptions.headers = requestOptions.headers || {};
            requestOptions.headers["X-Requested-With"] = "XMLHttpRequest";
            return fetch(url, requestOptions).then(function (response) {
                return response.json().then(function (payload) {
                    if (!response.ok || payload.ok === false) {
                        throw new Error((payload && payload.message) || "Request failed.");
                    }
                    return payload;
                });
            });
        }

        function isMobileLayout() {
            return mobileQuery.matches;
        }

        function buildThreadKey(type, target) {
            return type && target ? type + "::" + target : "";
        }

        function buildOverviewThreadKey(item) {
            if (!item) {
                return "";
            }
            if (item.thread_type === "direct" && item.target_username) {
                return buildThreadKey(item.thread_type, item.target_username);
            }
            return buildThreadKey(item.thread_type, item.room_key || item.title || "");
        }

        function getOverviewThreads(overview) {
            return []
                .concat((overview && overview.channels) || [])
                .concat((overview && overview.role_groups) || [])
                .concat((overview && overview.direct_threads) || []);
        }

        function buildOverviewSnapshot(overview) {
            var snapshot = {};
            getOverviewThreads(overview).forEach(function (item) {
                var key = buildOverviewThreadKey(item);
                if (!key) {
                    return;
                }
                snapshot[key] = {
                    key: key,
                    roomKey: item.room_key || "",
                    threadType: item.thread_type || "",
                    target: item.thread_type === "direct" ? (item.target_username || "") : (item.room_key || ""),
                    title: item.title || "Conversation",
                    senderName: item.last_message_sender_name || "",
                    senderUsername: item.last_message_sender_username || "",
                    preview: item.last_message_preview || "",
                    lastMessageAt: item.last_message_at || "",
                    unreadCount: Number(item.unread_count || 0),
                    isSelf: !!item.last_message_is_self
                };
            });
            return snapshot;
        }

        function canUseBrowserNotifications() {
            return typeof window !== "undefined" && "Notification" in window;
        }

        function requestBrowserNotificationPermission() {
            if (!canUseBrowserNotifications() || Notification.permission !== "default") {
                return;
            }
            Notification.requestPermission().catch(function () {
                return;
            });
        }

        function shouldShowLiveNotification(threadState) {
            if (!threadState || !canUseBrowserNotifications() || Notification.permission !== "granted") {
                return false;
            }
            if (threadState.isSelf || !threadState.lastMessageAt || threadState.unreadCount <= 0) {
                return false;
            }
            if (!document.hidden && state.chatOpen && state.currentView === "thread") {
                var activeKey = buildThreadKey(state.activeType, state.activeTarget);
                if (activeKey && activeKey === threadState.key) {
                    return false;
                }
            }
            return document.hidden || !state.chatOpen || buildThreadKey(state.activeType, state.activeTarget) !== threadState.key;
        }

        function showLiveChatNotification(threadState) {
            if (!shouldShowLiveNotification(threadState)) {
                return;
            }
            if (state.liveNotifications[threadState.key] === threadState.lastMessageAt) {
                return;
            }

            state.liveNotifications[threadState.key] = threadState.lastMessageAt;
            var body = threadState.preview || "New message received.";
            if (threadState.senderName) {
                body = threadState.senderName + ": " + body;
            }
            var notification = new Notification(threadState.title || "New chat message", {
                body: body,
                tag: "split-chat-" + threadState.key,
                silent: false
            });
            notification.onclick = function () {
                window.focus();
                openConversation(threadState.threadType, threadState.target || threadState.roomKey).catch(function () {
                    return;
                });
                notification.close();
            };
        }

        function maybeNotifyOverviewChanges(nextOverview) {
            var nextSnapshot = buildOverviewSnapshot(nextOverview);
            if (!state.hasBootstrappedOverview) {
                state.overviewThreadSnapshot = nextSnapshot;
                state.hasBootstrappedOverview = true;
                return;
            }

            Object.keys(nextSnapshot).forEach(function (key) {
                var previous = state.overviewThreadSnapshot[key];
                var current = nextSnapshot[key];
                var lastMessageChanged = !previous || previous.lastMessageAt !== current.lastMessageAt;
                var unreadIncreased = !previous || current.unreadCount > previous.unreadCount;
                if (lastMessageChanged && unreadIncreased) {
                    showLiveChatNotification(current);
                }
            });

            state.overviewThreadSnapshot = nextSnapshot;
        }

        function getLoadedOldestId() {
            return state.threadMessages.length ? state.threadMessages[0].id : null;
        }

        function getLoadedNewestId() {
            return state.threadMessages.length ? state.threadMessages[state.threadMessages.length - 1].id : null;
        }

        function isFeedNearBottom() {
            if (!refs.feed) {
                return true;
            }
            return refs.feed.scrollHeight - refs.feed.scrollTop - refs.feed.clientHeight < 88;
        }

        function scrollFeedToBottom() {
            if (refs.feed) {
                refs.feed.scrollTop = refs.feed.scrollHeight;
            }
        }

        function autoResizeComposer() {
            if (!refs.composeInput) {
                return;
            }
            refs.composeInput.style.height = "auto";
            refs.composeInput.style.overflowY = "hidden";
            refs.composeInput.style.height = Math.min(
                refs.composeInput.scrollHeight,
                isMobileLayout() ? 160 : 220
            ) + "px";
            if (refs.composeInput.scrollHeight > parseInt(refs.composeInput.style.height, 10)) {
                refs.composeInput.style.overflowY = "auto";
            }
        }

        function saveCurrentDraft() {
            var draftKey = buildThreadKey(state.activeType, state.activeTarget);
            if (!draftKey || !refs.composeInput) {
                return;
            }
            state.drafts[draftKey] = refs.composeInput.value || "";
        }

        function restoreCurrentDraft() {
            var draftKey = buildThreadKey(state.activeType, state.activeTarget);
            if (!refs.composeInput) {
                return;
            }
            refs.composeInput.value = draftKey && state.drafts[draftKey] ? state.drafts[draftKey] : "";
            autoResizeComposer();
        }

        function clearCurrentDraft() {
            var draftKey = buildThreadKey(state.activeType, state.activeTarget);
            if (draftKey) {
                delete state.drafts[draftKey];
            }
        }

        function renderSyncStatus() {
            if (!refs.syncStatus) {
                return;
            }
            refs.syncStatus.textContent = formatSyncLabel(state.syncState, state.lastSyncAt);
            refs.syncStatus.classList.remove("is-syncing", "is-error");
            if (state.syncState === "syncing") {
                refs.syncStatus.classList.add("is-syncing");
            } else if (state.syncState === "error") {
                refs.syncStatus.classList.add("is-error");
            }
        }

        function setSyncState(nextState) {
            state.syncState = nextState || "idle";
            if (state.syncState === "synced") {
                state.lastSyncAt = Date.now();
            }
            renderSyncStatus();
        }

        function syncAppShellLayout() {
            var appShell = window.AppShell;
            if (!appShell) {
                return;
            }

            if (appShell.isMobile && appShell.isMobile()) {
                if (appShell.closeSidebar) {
                    appShell.closeSidebar();
                }
                state.collapsedSidebarForChat = false;
                return;
            }

            state.collapsedSidebarForChat = false;
        }

        function syncOpenState() {
            var showThread = state.chatOpen && state.currentView === "thread";
            var showList = state.chatOpen && !showThread;

            root.classList.toggle("is-open", state.chatOpen);
            root.classList.toggle("is-thread-view", showThread);
            root.classList.toggle("is-list-view", showList);

            if (refs.chatTrigger) {
                refs.chatTrigger.classList.toggle("is-active", state.chatOpen);
            }
            if (refs.chatPanel) {
                refs.chatPanel.setAttribute("aria-hidden", state.chatOpen ? "false" : "true");
            }
            if (refs.browser) {
                refs.browser.hidden = !state.chatOpen;
            }
            if (refs.threadPanel) {
                refs.threadPanel.hidden = !state.chatOpen;
            }

            syncAppShellLayout();
        }

        function setView(viewName) {
            state.currentView = viewName === "thread" && state.activeType ? "thread" : "list";
            if (state.currentView !== "thread") {
                state.settingsOpen = false;
                if (refs.channelForm) {
                    refs.channelForm.hidden = true;
                }
            }
            syncOpenState();
            updateComposerAvailability();
            syncComposerState();
            syncJumpLatestVisibility();
        }

        function setChatOpen(open, options) {
            var config = options || {};
            state.chatOpen = !!open;
            if (!state.chatOpen) {
                syncOpenState();
                return;
            }

            requestBrowserNotificationPermission();

            if (state.currentView === "thread" && !state.activeType) {
                state.currentView = "list";
            }

            syncOpenState();

            if (config.skipRefresh) {
                return;
            }

            if (state.currentView === "thread" && state.activeType && state.activeTarget) {
                refreshActiveThread();
                return;
            }

            refreshOverview();
            if (refs.chatSearch && !isMobileLayout()) {
                refs.chatSearch.focus();
            }
        }

        function updateUnreadBadge(total) {
            var unread = Number(total || 0);
            if (refs.chatBadge) {
                refs.chatBadge.hidden = unread <= 0;
                refs.chatBadge.textContent = unread > 99 ? "99+" : String(unread);
            }
            if (refs.chatSummary) {
                refs.chatSummary.textContent = unread <= 0
                    ? "All caught up"
                    : (unread === 1 ? "1 unread conversation" : unread + " unread conversations");
            }
        }

        function updateStatChips(overview) {
            var unreadTotal = Number((overview && overview.unread_total) || 0);
            var onlineTotal = overview && overview.users
                ? overview.users.filter(function (item) { return item.presence === "online"; }).length
                : 0;

            if (refs.chatStatUnread) {
                refs.chatStatUnread.textContent = unreadTotal > 99 ? "99+" : String(unreadTotal);
            }
            if (refs.chatStatOnline) {
                refs.chatStatOnline.textContent = onlineTotal > 99 ? "99+" : String(onlineTotal);
            }
        }

        function updateFavoriteButtonLabel(button, isActive) {
            if (!button) {
                return;
            }
            button.dataset.chatFavoriteActive = isActive ? "true" : "false";
            if (button.classList.contains("chat-list-item-action-favorite")) {
                button.textContent = isActive ? "★" : "☆";
                button.classList.toggle("is-active", isActive);
                return;
            }
            button.textContent = isActive ? "Remove Favorite" : "Add to Favorites";
        }

        function syncProfileFavoriteButtons() {
            var favoriteUsernames = {};
            ((state.overview && state.overview.favorites) || []).forEach(function (item) {
                favoriteUsernames[String(item.username || "").toLowerCase()] = true;
            });

            Array.prototype.slice.call(document.querySelectorAll("[data-chat-favorite-toggle]")).forEach(function (button) {
                var targetUsername = String(button.getAttribute("data-chat-favorite-toggle") || "").trim().toLowerCase();
                updateFavoriteButtonLabel(button, !!favoriteUsernames[targetUsername]);
            });
        }

        function sendFavoriteToggle(username, shouldFavorite) {
            var favoriteToggleUrl = root.dataset.favoriteToggleUrl;
            if (!favoriteToggleUrl) {
                return Promise.reject(new Error("Favorite toggle is unavailable."));
            }
            var formData = new FormData();
            formData.append("username", username);
            formData.append("state", shouldFavorite ? "on" : "off");
            return fetchJson(favoriteToggleUrl, {
                method: "POST",
                body: formData
            }).then(function (payload) {
                syncOverview(payload.overview || {});
                return payload;
            });
        }

        function toggleFavorite(username, shouldFavorite, triggerButton) {
            if (!username) {
                return Promise.resolve();
            }
            if (triggerButton) {
                triggerButton.disabled = true;
            }
            return sendFavoriteToggle(username, shouldFavorite)
                .then(function (payload) {
                    updateFavoriteButtonLabel(triggerButton, shouldFavorite);
                    setComposeStatus(payload.message || "", "success");
                    return payload;
                })
                .catch(function (error) {
                    setComposeStatus(error.message || "Unable to update favorite.", "error");
                    throw error;
                })
                .finally(function () {
                    if (triggerButton) {
                        triggerButton.disabled = false;
                    }
                });
        }

        function getSearchText(item) {
            return normalizeSearch([
                item.title,
                item.subtitle,
                item.note,
                item.eyebrowText,
                item.username,
                item.pill,
                item.description,
                item.searchBlob
            ].join(" "));
        }

        function getSearchRank(item, term) {
            var searchTerm = normalizeSearch(term);
            if (!searchTerm) {
                return 0;
            }

            var username = normalizeSearch(item.username);
            var primaryName = normalizeSearch(item.title);
            var secondaryName = normalizeSearch(item.subtitle);
            var combined = getSearchText(item);
            var compactTerm = searchTerm.replace(/\s+/g, "");
            var compactCombined = combined.replace(/\s+/g, "");
            var tokens = searchTerm.split(/\s+/).filter(Boolean);

            if (username && username === searchTerm) {
                return 0;
            }
            if (primaryName && primaryName === searchTerm) {
                return 1;
            }
            if (secondaryName && secondaryName === searchTerm) {
                return 2;
            }
            if (username && username.indexOf(searchTerm) !== -1) {
                return 10 + username.indexOf(searchTerm);
            }
            if (primaryName && primaryName.indexOf(searchTerm) !== -1) {
                return 20 + primaryName.indexOf(searchTerm);
            }
            if (secondaryName && secondaryName.indexOf(searchTerm) !== -1) {
                return 40 + secondaryName.indexOf(searchTerm);
            }
            if (compactTerm && compactCombined.indexOf(compactTerm) !== -1) {
                return 60 + compactCombined.indexOf(compactTerm);
            }
            if (tokens.length && tokens.every(function (token) { return combined.indexOf(token) !== -1; })) {
                return 90 + combined.indexOf(tokens[0]);
            }
            return -1;
        }

        function sortSearchItems(items, term) {
            return (items || []).slice().sort(function (left, right) {
                var leftRank = getSearchRank(left, term);
                var rightRank = getSearchRank(right, term);
                if (leftRank !== rightRank) {
                    return leftRank - rightRank;
                }
                if (!!left.isFavorite !== !!right.isFavorite) {
                    return left.isFavorite ? -1 : 1;
                }
                return String(left.title || "").localeCompare(String(right.title || ""));
            });
        }

        function formatPreviewLine(item) {
            var preview = item.last_message_preview || "No messages yet";
            if (!item.last_message_sender_name) {
                return preview;
            }

            if (item.thread_type === "direct") {
                return item.last_message_is_self ? "You: " + preview : preview;
            }

            return (item.last_message_is_self ? "You" : item.last_message_sender_name) + ": " + preview;
        }

        function formatPresenceNote(item) {
            if (!item) {
                return "";
            }
            if (item.presence === "online") {
                return "Online now";
            }
            return "Last active " + (formatLastActivity(item.last_seen_at || item.last_login_at) || "not available");
        }

        function buildUnifiedItems(overview) {
            var items = [];
            var directLookup = {};

            (overview.direct_threads || []).forEach(function (item) {
                directLookup[String(item.target_username || "").toLowerCase()] = true;
                var directDescription = normalizeThreadDescription(item.description);
                items.push({
                    type: "direct",
                    target: item.target_username,
                    title: item.title,
                    subtitle: joinBits([directDescription, buildHandle(item.target_username)]),
                    note: formatPreviewLine(item),
                    eyebrowText: formatPresenceNote(item),
                    unreadCount: Number(item.unread_count || 0),
                    timestamp: formatConversationTime(item.last_message_at),
                    pill: "Direct",
                    pillTone: "direct",
                    avatarText: getInitials(item.title, "DM"),
                    avatarUrl: item.avatar_url,
                    avatarTone: "direct",
                    status: item.presence || "",
                    isFavorite: !!item.is_favorite,
                    canFavorite: true,
                    username: item.target_username,
                    hasConversation: true,
                    description: directDescription,
                    sortTime: parseTimestamp(item.last_message_at),
                    searchBlob: [
                        directDescription,
                        item.target_username,
                        item.last_message_preview,
                        item.last_message_sender_name
                    ].join(" ")
                });
            });

            (overview.channels || []).forEach(function (item) {
                var channelDescription = normalizeThreadDescription(item.description);
                items.push({
                    type: "channel",
                    target: item.room_key,
                    title: item.title,
                    subtitle: channelDescription || "Public channel",
                    note: formatPreviewLine(item),
                    eyebrowText: joinBits([
                        "Channel " + getChannelBadge(item.room_key),
                        item.member_count ? item.member_count + " members" : "Shared room"
                    ]),
                    unreadCount: Number(item.unread_count || 0),
                    timestamp: formatConversationTime(item.last_message_at),
                    pill: "Channel",
                    pillTone: "channel",
                    avatarText: getChannelBadge(item.room_key),
                    avatarUrl: "",
                    avatarTone: "channel",
                    status: "",
                    isFavorite: false,
                    canFavorite: false,
                    username: "",
                    hasConversation: true,
                    description: channelDescription,
                    sortTime: parseTimestamp(item.last_message_at),
                    searchBlob: [
                        channelDescription,
                        item.role_name,
                        item.last_message_preview,
                        item.last_message_sender_name
                    ].join(" ")
                });
            });

            (overview.role_groups || []).forEach(function (item) {
                var roleDescription = normalizeThreadDescription(item.description);
                items.push({
                    type: "role",
                    target: item.room_key,
                    title: item.title,
                    subtitle: roleDescription || (item.role_name ? item.role_name + " group" : "Restricted group"),
                    note: formatPreviewLine(item),
                    eyebrowText: joinBits([
                        item.role_name || "Role group",
                        item.member_count ? item.member_count + " members" : "Restricted"
                    ]),
                    unreadCount: Number(item.unread_count || 0),
                    timestamp: formatConversationTime(item.last_message_at),
                    pill: "Group",
                    pillTone: "group",
                    avatarText: getInitials(item.role_name || item.title, "RG"),
                    avatarUrl: "",
                    avatarTone: "group",
                    status: "",
                    isFavorite: false,
                    canFavorite: false,
                    username: "",
                    hasConversation: true,
                    description: roleDescription,
                    sortTime: parseTimestamp(item.last_message_at),
                    searchBlob: [
                        roleDescription,
                        item.role_name,
                        item.last_message_preview,
                        item.last_message_sender_name
                    ].join(" ")
                });
            });

            (overview.users || []).forEach(function (item) {
                var usernameKey = String(item.username || "").toLowerCase();
                if (directLookup[usernameKey]) {
                    return;
                }
                items.push({
                    type: "direct",
                    target: item.username,
                    title: item.fullname,
                    subtitle: joinBits([item.designation, buildHandle(item.username)]),
                    note: formatPresenceNote(item),
                    eyebrowText: "Start a direct conversation",
                    unreadCount: 0,
                    timestamp: formatConversationTime(item.last_seen_at || item.last_login_at),
                    pill: "Individual",
                    pillTone: "person",
                    avatarText: getInitials(item.fullname, "U"),
                    avatarUrl: item.avatar_url,
                    avatarTone: "person",
                    status: item.presence || "",
                    isFavorite: !!item.is_favorite,
                    canFavorite: true,
                    username: item.username,
                    hasConversation: false,
                    description: item.designation || "",
                    sortTime: parseTimestamp(item.last_seen_at || item.last_login_at),
                    searchBlob: [
                        item.fullname,
                        item.display_name,
                        item.designation,
                        item.username,
                        item.presence_label
                    ].join(" ")
                });
            });

            return items;
        }

        function sortUnifiedItems(items) {
            return (items || []).slice().sort(function (left, right) {
                if (!!left.hasConversation !== !!right.hasConversation) {
                    return left.hasConversation ? -1 : 1;
                }
                if (!left.hasConversation && !right.hasConversation) {
                    if (!!left.isFavorite !== !!right.isFavorite) {
                        return left.isFavorite ? -1 : 1;
                    }
                    if ((left.status === "online") !== (right.status === "online")) {
                        return left.status === "online" ? -1 : 1;
                    }
                    return String(left.title || "").localeCompare(String(right.title || ""));
                }

                var leftTime = left.sortTime ? left.sortTime.getTime() : 0;
                var rightTime = right.sortTime ? right.sortTime.getTime() : 0;
                if (leftTime !== rightTime) {
                    return rightTime - leftTime;
                }
                if (left.unreadCount !== right.unreadCount) {
                    return right.unreadCount - left.unreadCount;
                }
                return String(left.title || "").localeCompare(String(right.title || ""));
            });
        }

        function sortPeopleItems(items) {
            return (items || []).slice().sort(function (left, right) {
                if (!!left.isFavorite !== !!right.isFavorite) {
                    return left.isFavorite ? -1 : 1;
                }
                if (!!left.hasConversation !== !!right.hasConversation) {
                    return left.hasConversation ? -1 : 1;
                }
                var leftTime = left.sortTime ? left.sortTime.getTime() : 0;
                var rightTime = right.sortTime ? right.sortTime.getTime() : 0;
                if (leftTime !== rightTime) {
                    return rightTime - leftTime;
                }
                if ((left.status === "online") !== (right.status === "online")) {
                    return left.status === "online" ? -1 : 1;
                }
                return String(left.title || "").localeCompare(String(right.title || ""));
            });
        }

        function getFilteredItems() {
            var items = buildUnifiedItems(state.overview || {});

            items = items.filter(function (item) {
                if (state.filterMode === "unread") {
                    return item.hasConversation && item.unreadCount > 0;
                }
                if (state.filterMode === "channels") {
                    return item.type === "channel";
                }
                if (state.filterMode === "groups") {
                    return item.type === "role";
                }
                if (state.filterMode === "people") {
                    return item.type === "direct";
                }
                return true;
            });

            if (state.searchTerm) {
                items = items.filter(function (item) {
                    return getSearchRank(item, state.searchTerm) >= 0;
                });
                return sortSearchItems(items, state.searchTerm);
            }

            if (state.filterMode === "people") {
                return sortPeopleItems(items);
            }

            return sortUnifiedItems(items);
        }

        function getEmptyListLabel() {
            if (state.searchTerm) {
                return "No conversations or staff match your search.";
            }
            if (state.filterMode === "unread") {
                return "No unread conversations right now.";
            }
            if (state.filterMode === "channels") {
                return "No channels available.";
            }
            if (state.filterMode === "groups") {
                return "No role groups available.";
            }
            if (state.filterMode === "people") {
                return "No individuals available.";
            }
            return "No conversations available yet.";
        }

        function buildConversationRow(item) {
            var shell = createNode("div", "chat-list-item-shell");
            var button = createNode("button", "chat-list-item");
            button.type = "button";
            if (state.activeType === item.type && state.activeTarget === item.target) {
                button.classList.add("is-active");
            }
            if (item.unreadCount > 0) {
                button.classList.add("is-unread");
            }
            if (item.isFavorite) {
                button.classList.add("is-favorite");
            }

            var main = createNode("div", "chat-list-item-main");
            var avatar = createNode("span", "chat-list-item-avatar chat-list-item-avatar-" + item.avatarTone);
            applyAvatarFace(avatar, item.avatarUrl, item.avatarText);
            if (item.status) {
                avatar.appendChild(createNode("span", "chat-list-item-avatar-status" + (item.status === "online" ? " is-online" : "")));
            }
            main.appendChild(avatar);

            var copy = createNode("div", "chat-list-item-copy");
            var eyebrow = createNode("div", "chat-list-item-eyebrow");
            eyebrow.appendChild(createNode("span", "chat-list-pill is-" + item.pillTone, item.pill));
            if (item.eyebrowText) {
                eyebrow.appendChild(createNode(
                    "span",
                    "chat-list-item-eyebrow-text" + (item.status === "online" ? " is-online" : ""),
                    item.eyebrowText
                ));
            }
            copy.appendChild(eyebrow);

            var titleRow = createNode("div", "chat-list-item-row");
            titleRow.appendChild(createNode("div", "chat-list-item-title", item.title));
            var tail = createNode("div", "chat-list-item-tail");
            if (item.timestamp) {
                tail.appendChild(createNode("span", "chat-list-item-time", item.timestamp));
            }
            if (item.unreadCount > 0) {
                tail.appendChild(createNode("span", "chat-list-item-unread", item.unreadCount > 99 ? "99+" : String(item.unreadCount)));
            }
            titleRow.appendChild(tail);
            copy.appendChild(titleRow);

            if (item.subtitle) {
                copy.appendChild(createNode("div", "chat-list-item-subtitle", item.subtitle));
            }
            if (item.note) {
                copy.appendChild(createNode(
                    "div",
                    "chat-list-item-note" + (item.unreadCount > 0 ? " is-unread" : ""),
                    item.note
                ));
            }

            main.appendChild(copy);
            button.appendChild(main);
            button.addEventListener("click", function () {
                if (typeof button.blur === "function") {
                    button.blur();
                }
                openConversation(item.type, item.target).catch(function () {
                    return;
                });
            });
            shell.appendChild(button);

            if (item.canFavorite) {
                var actionButton = createNode(
                    "button",
                    "chat-list-item-action chat-list-item-action-favorite" + (item.isFavorite ? " is-active" : ""),
                    item.isFavorite ? "★" : "☆"
                );
                actionButton.type = "button";
                actionButton.title = item.isFavorite ? "Remove from favorites" : "Add to favorites";
                actionButton.setAttribute("aria-label", actionButton.title);
                actionButton.addEventListener("click", function (event) {
                    event.preventDefault();
                    event.stopPropagation();
                    toggleFavorite(item.username || item.target, !item.isFavorite, actionButton).catch(function () {
                        return;
                    });
                });
                shell.appendChild(actionButton);
            }

            return shell;
        }

        function renderUnifiedList() {
            if (!refs.unifiedList) {
                return;
            }
            refs.unifiedList.innerHTML = "";

            var items = getFilteredItems();
            if (!items.length) {
                refs.unifiedList.appendChild(createNode(
                    "div",
                    "chat-empty-state chat-empty-state-compact",
                    getEmptyListLabel()
                ));
                return;
            }

            items.forEach(function (item) {
                refs.unifiedList.appendChild(buildConversationRow(item));
            });
        }

        function renderProfileSearchPanels() {
            var searchPanels = Array.prototype.slice.call(document.querySelectorAll("[data-profile-chat-search]"));
            if (!searchPanels.length) {
                return;
            }

            searchPanels.forEach(function (panel) {
                var input = panel.querySelector("[data-profile-chat-search-input]");
                var results = panel.querySelector("[data-profile-chat-search-results]");
                if (!input || !results) {
                    return;
                }

                var term = normalizeSearch(input.value);
                results.innerHTML = "";
                if (!term) {
                    results.hidden = true;
                    return;
                }

                var matches = sortSearchItems(
                    buildUnifiedItems(state.overview || {}).filter(function (item) {
                        return item.type === "direct" && !item.hasConversation && getSearchRank(item, term) >= 0;
                    }),
                    term
                ).slice(0, 8);

                results.hidden = !matches.length;
                if (!matches.length) {
                    results.appendChild(createNode("div", "chat-empty-state chat-empty-state-compact", "No users match your search."));
                    results.hidden = false;
                    return;
                }

                matches.forEach(function (item) {
                    var row = createNode("div", "profile-chat-search-row");
                    var identity = createNode("button", "profile-chat-search-user");
                    identity.type = "button";
                    identity.appendChild(createNode("strong", "", item.title));
                    identity.appendChild(createNode("span", "", joinBits([buildHandle(item.username), item.description])));
                    identity.addEventListener("click", function () {
                        openDirectConversation(item.username).catch(function (error) {
                            setComposeStatus(error.message, "error");
                        });
                    });
                    row.appendChild(identity);

                    var favoriteButton = createNode(
                        "button",
                        "chat-list-item-action chat-list-item-action-favorite" + (item.isFavorite ? " is-active" : ""),
                        item.isFavorite ? "★" : "☆"
                    );
                    favoriteButton.type = "button";
                    favoriteButton.addEventListener("click", function () {
                        toggleFavorite(item.username, !item.isFavorite, favoriteButton).catch(function () {
                            return;
                        });
                    });
                    row.appendChild(favoriteButton);
                    results.appendChild(row);
                });
            });
        }

        function findOverviewThread(type, target) {
            if (!state.overview) {
                return null;
            }
            if (type === "channel") {
                return (state.overview.channels || []).find(function (item) {
                    return item.room_key === target;
                }) || null;
            }
            if (type === "role") {
                return (state.overview.role_groups || []).find(function (item) {
                    return item.room_key === target;
                }) || null;
            }
            if (type === "direct") {
                return (state.overview.direct_threads || []).find(function (item) {
                    return item.target_username === target;
                }) || null;
            }
            return null;
        }

        function syncActiveThreadFromOverview() {
            if (!state.activeThread || !state.activeType || !state.activeTarget) {
                return;
            }

            var match = findOverviewThread(state.activeType, state.activeTarget);
            if (!match) {
                return;
            }

            state.activeThread.member_count = match.member_count || state.activeThread.member_count || 0;
            if (state.activeType === "direct") {
                state.activeThread.title = match.title || state.activeThread.title;
                state.activeThread.description = match.description || state.activeThread.description;
                state.activeThread.target_username = match.target_username || state.activeThread.target_username;
                state.activeThread.avatar_url = match.avatar_url || state.activeThread.avatar_url || "";
                state.activeThread.profile_url = match.profile_url || state.activeThread.profile_url || "";
                state.activeThread.presence = {
                    status: match.presence,
                    status_label: match.presence_label,
                    is_online: match.presence === "online",
                    last_seen_at: match.last_seen_at,
                    last_login_at: match.last_login_at
                };
            }

            applyThreadHeader(state.activeThread);
        }

        function syncOverview(overview) {
            maybeNotifyOverviewChanges(overview);
            state.overview = overview || {
                channels: [],
                role_groups: [],
                direct_threads: [],
                users: [],
                favorites: [],
                unread_total: 0
            };

            updateUnreadBadge(state.overview.unread_total);
            updateStatChips(state.overview);
            renderUnifiedList();
            syncProfileFavoriteButtons();
            renderProfileSearchPanels();
            syncActiveThreadFromOverview();
        }

        function setComposeStatus(message, tone) {
            if (!refs.composeStatus) {
                return;
            }
            refs.composeStatus.textContent = message || "";
            refs.composeStatus.classList.remove("is-error", "is-success");
            if (tone === "error" || tone === "success") {
                refs.composeStatus.classList.add("is-" + tone);
            }
        }

        function clearComposer() {
            clearCurrentDraft();
            if (refs.composeInput) {
                refs.composeInput.value = "";
            }
            autoResizeComposer();
            if (refs.fileInput) {
                refs.fileInput.value = "";
            }
            if (refs.fileName) {
                refs.fileName.textContent = "No file selected";
                refs.fileName.hidden = true;
            }
            if (refs.filePreview) {
                refs.filePreview.hidden = true;
            }
            if (refs.fileChip) {
                refs.fileChip.textContent = "No file selected";
            }
            setComposeStatus("");
            syncComposerState();
        }

        function updateFilePreview() {
            var fileName = refs.fileInput && refs.fileInput.files && refs.fileInput.files.length
                ? refs.fileInput.files[0].name
                : "";
            if (refs.fileName) {
                refs.fileName.textContent = fileName || "No file selected";
                refs.fileName.hidden = !fileName;
            }
            if (refs.fileChip) {
                refs.fileChip.textContent = fileName || "No file selected";
            }
            if (refs.filePreview) {
                refs.filePreview.hidden = !fileName;
            }
            syncComposerState();
        }

        function syncComposerState() {
            if (!refs.compose || !refs.composeInput) {
                return;
            }
            var hasThread = !!state.activeThread;
            var hasFocus = !!refs.compose.contains(document.activeElement);
            var hasDraft = !!String(refs.composeInput.value || "").trim();
            var hasFile = !!(refs.fileInput && refs.fileInput.files && refs.fileInput.files.length);
            var shouldExpand = hasThread && (hasFocus || hasDraft || hasFile || state.sending);

            refs.compose.classList.toggle("is-expanded", shouldExpand);
            refs.compose.classList.toggle("has-file", hasFile);
        }

        function updateComposerAvailability() {
            if (!refs.compose || !refs.composeInput || !refs.fileInput) {
                return;
            }
            var hasThread = !!state.activeThread;
            refs.compose.classList.toggle("is-disabled", !hasThread);
            refs.composeInput.disabled = !hasThread || state.sending;
            refs.fileInput.disabled = !hasThread || state.sending;
            refs.composeInput.placeholder = hasThread ? "Write a message..." : "Select a conversation first.";

            if (refs.sendButton) {
                refs.sendButton.disabled = !hasThread || state.sending;
                refs.sendButton.textContent = state.sending ? "Sending..." : "Send";
            }
            if (refs.fileTrigger) {
                refs.fileTrigger.classList.toggle("is-disabled", !hasThread || state.sending);
            }
            syncComposerState();
        }

        function setSettingsOpen(open) {
            var canEdit = !!(state.activeThread && state.activeThread.editable);
            state.settingsOpen = !!open && canEdit;
            if (refs.channelForm) {
                refs.channelForm.hidden = !state.settingsOpen;
            }
            if (refs.editToggle) {
                refs.editToggle.hidden = !canEdit;
                refs.editToggle.classList.toggle("is-active", state.settingsOpen);
            }
        }

        function applyThreadHeader(thread) {
            if (!thread) {
                if (refs.title) {
                    refs.title.textContent = "Select a conversation";
                }
                if (refs.subtitle) {
                    refs.subtitle.textContent = "Choose a message from the list.";
                }
                if (refs.threadAvatar) {
                    refs.threadAvatar.className = "chat-thread-avatar";
                    refs.threadAvatar.classList.remove("has-image");
                }
                if (refs.threadAvatarText) {
                    refs.threadAvatarText.textContent = "?";
                }
                if (refs.threadAvatarImage) {
                    refs.threadAvatarImage.hidden = true;
                    refs.threadAvatarImage.removeAttribute("src");
                }
                if (refs.threadAvatarStatus) {
                    refs.threadAvatarStatus.hidden = true;
                    refs.threadAvatarStatus.classList.remove("is-online");
                }
                if (refs.composeType) {
                    refs.composeType.value = "";
                }
                if (refs.composeTarget) {
                    refs.composeTarget.value = "";
                }
                if (refs.channelRoomKey) {
                    refs.channelRoomKey.value = "";
                }
                if (refs.channelTitleInput) {
                    refs.channelTitleInput.value = "";
                }
                if (refs.channelDescriptionInput) {
                    refs.channelDescriptionInput.value = "";
                }
                if (refs.composeInput) {
                    refs.composeInput.value = "";
                    autoResizeComposer();
                }
                setSettingsOpen(false);
                updateComposerAvailability();
                return;
            }

            var subtitleBits = [];
            var avatarText = "?";
            var avatarUrl = "";
            var avatarTone = "direct";
            var directStatus = "";
            var normalizedDescription = normalizeThreadDescription(thread.description);

            if (thread.thread_type === "channel") {
                subtitleBits = [
                    normalizedDescription,
                    thread.member_count ? thread.member_count + " members" : "Channel"
                ];
                avatarText = getChannelBadge(thread.room_key);
                avatarTone = "channel";
            } else if (thread.thread_type === "role") {
                subtitleBits = [
                    normalizedDescription,
                    thread.member_count ? thread.member_count + " members" : "Group"
                ];
                avatarText = getInitials(thread.title, "RG");
                avatarTone = "group";
            } else if (thread.thread_type === "direct") {
                subtitleBits = [
                    normalizedDescription,
                    buildHandle(thread.target_username),
                    thread.presence && thread.presence.is_online
                        ? "Online now"
                        : (thread.presence && (thread.presence.last_seen_at || thread.presence.last_login_at)
                            ? "Last active " + formatLastActivity(thread.presence.last_seen_at || thread.presence.last_login_at)
                            : "")
                ];
                avatarText = getInitials(thread.title, "DM");
                avatarUrl = thread.avatar_url || "";
                avatarTone = "direct";
                directStatus = thread.presence ? thread.presence.status : "";
            }

            if (refs.title) {
                refs.title.textContent = thread.title || "Conversation";
            }
            if (refs.subtitle) {
                refs.subtitle.textContent = joinBits(subtitleBits) || "Conversation ready.";
            }
            if (refs.threadAvatar) {
                refs.threadAvatar.className = "chat-thread-avatar chat-thread-avatar-" + avatarTone;
            }
            if (refs.threadAvatarText) {
                refs.threadAvatarText.textContent = avatarText;
            }
            if (refs.threadAvatarImage) {
                if (avatarUrl) {
                    refs.threadAvatarImage.src = avatarUrl;
                    refs.threadAvatarImage.hidden = false;
                    if (refs.threadAvatar) {
                        refs.threadAvatar.classList.add("has-image");
                    }
                } else {
                    refs.threadAvatarImage.hidden = true;
                    refs.threadAvatarImage.removeAttribute("src");
                    if (refs.threadAvatar) {
                        refs.threadAvatar.classList.remove("has-image");
                    }
                }
            }
            if (refs.threadAvatarStatus) {
                refs.threadAvatarStatus.hidden = !directStatus;
                refs.threadAvatarStatus.classList.toggle("is-online", directStatus === "online");
            }
            if (refs.channelRoomKey) {
                refs.channelRoomKey.value = thread.editable ? thread.room_key : "";
            }
            if (refs.channelTitleInput) {
                refs.channelTitleInput.value = thread.editable ? (thread.title || "") : "";
            }
            if (refs.channelDescriptionInput) {
                refs.channelDescriptionInput.value = thread.editable ? (thread.description || "") : "";
            }
            if (refs.composeType) {
                refs.composeType.value = thread.thread_type;
            }
            if (refs.composeTarget) {
                refs.composeTarget.value = thread.thread_type === "direct" ? thread.target_username : thread.room_key;
            }

            setSettingsOpen(state.settingsOpen);
            restoreCurrentDraft();
            updateComposerAvailability();
        }

        function showThreadLoading(message) {
            applyThreadHeader(null);
            if (refs.feed) {
                refs.feed.innerHTML = "";
                refs.feed.appendChild(createNode("div", "chat-empty-state", message || "Loading conversation..."));
            }
            if (refs.threadTools) {
                refs.threadTools.hidden = true;
            }
            if (refs.jumpLatest) {
                refs.jumpLatest.hidden = true;
            }
        }

        function buildAttachmentNode(attachment) {
            var attachmentNode = createNode("div", "chat-attachment");
            var attachmentLink = createNode("a", "chat-attachment-link");
            attachmentLink.href = attachment.url;
            attachmentLink.target = "_blank";
            attachmentLink.rel = "noopener noreferrer";

            var attachmentCopy = createNode("span", "chat-attachment-link-copy");
            attachmentCopy.appendChild(createNode(
                "span",
                "chat-attachment-kind",
                attachment.kind === "image" ? "Image" : "File"
            ));
            attachmentCopy.appendChild(createNode("span", "chat-attachment-name", attachment.name));
            attachmentLink.appendChild(attachmentCopy);
            attachmentNode.appendChild(attachmentLink);

            if (attachment.kind === "image") {
                var imageLink = createNode("a", "chat-attachment-preview");
                imageLink.href = attachment.url;
                imageLink.target = "_blank";
                imageLink.rel = "noopener noreferrer";
                var image = createNode("img");
                image.src = attachment.url;
                image.alt = attachment.name;
                image.loading = "lazy";
                imageLink.appendChild(image);
                attachmentNode.appendChild(imageLink);
            }

            return attachmentNode;
        }

        function buildMessageStamp(message) {
            var labels = [];
            if (message.is_deleted) {
                labels.push("Deleted");
            } else if (message.is_edited) {
                labels.push("Edited");
            }
            labels.push(formatTimeOnly(message.created_at));
            return labels.join(" | ");
        }

        function buildMessageNode(thread, message, options) {
            var layout = options || {};
            var showAuthor = thread.thread_type !== "direct" && !message.is_self && !layout.continuesFromPrevious;
            var shell = createNode(
                "div",
                "chat-message-shell" +
                    (message.is_self ? " is-self" : "") +
                    (layout.continuesFromPrevious ? " is-continued" : "")
            );

            if (!message.is_self) {
                var avatarNode;
                shell.appendChild(
                    layout.showAvatar
                        ? (function () {
                            avatarNode = createNode(message.sender_profile_url ? "a" : "span", "chat-message-avatar");
                            if (message.sender_profile_url) {
                                avatarNode.href = message.sender_profile_url;
                            }
                            applyAvatarFace(
                                avatarNode,
                                message.sender_avatar_url,
                                message.sender_avatar_initials || getInitials(message.sender_fullname, "U")
                            );
                            return avatarNode;
                        })()
                        : createNode("span", "chat-message-avatar-spacer")
                );
            }

            var stack = createNode("div", "chat-message-stack");
            if (showAuthor) {
                if (message.sender_profile_url) {
                    var authorLink = createNode("a", "chat-message-author-line chat-message-author-link", message.sender_fullname);
                    authorLink.href = message.sender_profile_url;
                    stack.appendChild(authorLink);
                } else {
                    stack.appendChild(createNode("div", "chat-message-author-line", message.sender_fullname));
                }
            }

            var bubble = createNode(
                "article",
                "chat-message" +
                    (message.is_self ? " is-self" : "") +
                    (layout.continuesFromPrevious ? " is-continued-top" : "") +
                    (layout.continuesToNext ? " is-continued-bottom" : "") +
                    (!message.body_html && message.attachment ? " is-attachment-only" : "")
            );
            bubble.title = formatLastActivity(message.created_at) || message.created_at;

            if (message.body_html) {
                var body = createNode("div", "chat-message-body");
                body.innerHTML = message.body_html;
                bubble.appendChild(body);
            }

            if (message.attachment) {
                bubble.appendChild(buildAttachmentNode(message.attachment));
            }

            stack.appendChild(bubble);
            if (!message.is_deleted && (message.can_edit || message.can_delete)) {
                var actionRow = createNode("div", "chat-message-actions" + (message.is_self ? " is-self" : ""));
                if (message.can_edit) {
                    var editButton = createNode("button", "chat-message-action", "Edit");
                    editButton.type = "button";
                    editButton.setAttribute("data-chat-edit-message", String(message.id));
                    actionRow.appendChild(editButton);
                }
                if (message.can_delete) {
                    var deleteButton = createNode("button", "chat-message-action chat-message-action-danger", "Delete");
                    deleteButton.type = "button";
                    deleteButton.setAttribute("data-chat-delete-message", String(message.id));
                    actionRow.appendChild(deleteButton);
                }
                stack.appendChild(actionRow);
            }
            if (!layout.continuesToNext) {
                stack.appendChild(createNode(
                    "div",
                    "chat-message-stamp" + (message.is_self ? " is-self" : ""),
                    buildMessageStamp(message)
                ));
            }
            shell.appendChild(stack);
            return shell;
        }

        function renderThreadMessages() {
            if (!refs.feed) {
                return;
            }
            refs.feed.innerHTML = "";

            if (!state.activeThread) {
                refs.feed.appendChild(createNode("div", "chat-empty-state", "Messages will appear here."));
                syncJumpLatestVisibility();
                return;
            }

            if (!state.threadMessages.length) {
                refs.feed.appendChild(createNode("div", "chat-empty-state", "No messages yet. Start the conversation."));
                syncJumpLatestVisibility();
                return;
            }

            var lastDateKey = "";
            state.threadMessages.forEach(function (message, index) {
                var previousMessage = index > 0 ? state.threadMessages[index - 1] : null;
                var nextMessage = index < state.threadMessages.length - 1 ? state.threadMessages[index + 1] : null;
                var continuesFromPrevious = canGroupMessages(previousMessage, message);
                var continuesToNext = canGroupMessages(message, nextMessage);
                var currentDateKey = getDateKey(message.created_at);
                if (currentDateKey && currentDateKey !== lastDateKey) {
                    var divider = createNode("div", "chat-date-divider");
                    divider.appendChild(createNode("span", "", formatDateDivider(message.created_at)));
                    refs.feed.appendChild(divider);
                    lastDateKey = currentDateKey;
                }

                refs.feed.appendChild(buildMessageNode(state.activeThread, message, {
                    continuesFromPrevious: continuesFromPrevious,
                    continuesToNext: continuesToNext,
                    showAvatar: !message.is_self && !continuesToNext
                }));
            });

            syncJumpLatestVisibility();
        }

        function updateThreadTools() {
            if (!refs.threadTools || !refs.loadOlder) {
                return;
            }
            var canLoadOlder = !!(state.activeThread && state.threadMeta && state.threadMeta.has_more_before);
            refs.threadTools.hidden = !canLoadOlder;
            refs.loadOlder.hidden = !canLoadOlder;
            refs.loadOlder.disabled = state.loadingOlder;
            refs.loadOlder.textContent = state.loadingOlder ? "Loading..." : "Load older messages";
        }

        function syncJumpLatestVisibility() {
            if (!refs.jumpLatest) {
                return;
            }
            if (!state.activeThread || !state.threadMessages.length || !refs.feed) {
                refs.jumpLatest.hidden = true;
                return;
            }
            if (isFeedNearBottom()) {
                state.unseenCount = 0;
                refs.jumpLatest.hidden = true;
                return;
            }
            refs.jumpLatest.hidden = false;
            refs.jumpLatest.textContent = state.unseenCount > 0
                ? (state.unseenCount === 1 ? "1 new message" : state.unseenCount + " new messages")
                : "Jump to latest";
        }

        function reconcileThreadMeta() {
            if (!state.threadMeta) {
                return;
            }

            var loadedOldestId = getLoadedOldestId();
            var loadedNewestId = getLoadedNewestId();
            state.threadMeta.window_oldest_id = loadedOldestId;
            state.threadMeta.window_newest_id = loadedNewestId;
            state.threadMeta.has_more_before = !!(
                loadedOldestId &&
                state.threadMeta.thread_oldest_id &&
                loadedOldestId > state.threadMeta.thread_oldest_id
            );
            state.threadMeta.has_more_after = !!(
                loadedNewestId &&
                state.threadMeta.thread_newest_id &&
                loadedNewestId < state.threadMeta.thread_newest_id
            );
        }

        function applyThreadPayload(payload, mode) {
            state.activeThread = payload.thread;
            state.threadMeta = Object.assign({}, state.threadMeta || {}, payload.message_meta || {});

            if (mode === "prepend") {
                state.threadMessages = mergeMessages(payload.messages || [], state.threadMessages);
            } else if (mode === "append") {
                state.threadMessages = mergeMessages(state.threadMessages, payload.messages || []);
            } else {
                state.threadMessages = (payload.messages || []).slice();
            }

            reconcileThreadMeta();
            applyThreadHeader(state.activeThread);
            renderThreadMessages();
            updateThreadTools();
        }

        function loadThread(type, target, options) {
            if (!type || !target) {
                return Promise.resolve();
            }

            var config = options || {};
            var sameThread = state.activeType === type && state.activeTarget === target;
            var mode = config.mode || "replace";
            var shouldStickToBottom = !!config.scrollToBottom;
            var previousMetrics = null;
            var wasNearBottom = sameThread ? isFeedNearBottom() : true;

            if (!sameThread) {
                saveCurrentDraft();
                if (refs.fileInput) {
                    refs.fileInput.value = "";
                }
                updateFilePreview();
                setComposeStatus("");
                state.unseenCount = 0;
            }

            if (sameThread && refs.feed) {
                previousMetrics = {
                    top: refs.feed.scrollTop,
                    height: refs.feed.scrollHeight
                };
            }

            state.activeType = type;
            state.activeTarget = target;
            setSyncState("syncing");

            var url = new URL(root.dataset.threadUrl, window.location.origin);
            url.searchParams.set("type", type);
            url.searchParams.set("target", target);
            url.searchParams.set("limit", String(config.limit || (mode === "append" ? 80 : 40)));
            if (config.beforeId) {
                url.searchParams.set("before_id", String(config.beforeId));
            }
            if (config.afterId) {
                url.searchParams.set("after_id", String(config.afterId));
            }

            return fetchJson(url.toString()).then(function (payload) {
                var incomingCount = Number((payload.messages || []).length);
                syncOverview(payload.overview);

                if (mode === "append" && !incomingCount) {
                    state.activeThread = payload.thread;
                    state.threadMeta = Object.assign({}, state.threadMeta || {}, payload.message_meta || {});
                    reconcileThreadMeta();
                    applyThreadHeader(state.activeThread);
                    updateThreadTools();
                    syncJumpLatestVisibility();
                    setSyncState("synced");
                    return payload;
                }

                applyThreadPayload(payload, mode);

                if (mode === "prepend" && previousMetrics) {
                    refs.feed.scrollTop = previousMetrics.top + (refs.feed.scrollHeight - previousMetrics.height);
                } else if (mode === "append" && sameThread && !shouldStickToBottom && !wasNearBottom) {
                    if (previousMetrics) {
                        refs.feed.scrollTop = previousMetrics.top;
                    }
                    state.unseenCount += incomingCount;
                } else if (shouldStickToBottom || mode === "replace" || !sameThread || wasNearBottom) {
                    scrollFeedToBottom();
                    state.unseenCount = 0;
                } else if (previousMetrics) {
                    refs.feed.scrollTop = previousMetrics.top;
                }

                syncJumpLatestVisibility();
                setSyncState("synced");
                return payload;
            }).catch(function (error) {
                setSettingsOpen(false);
                state.activeThread = null;
                state.threadMessages = [];
                state.threadMeta = null;
                state.activeType = "";
                state.activeTarget = "";
                state.unseenCount = 0;
                applyThreadHeader(null);
                setView("list");
                setComposeStatus(error.message || "Unable to load this conversation.", "error");
                setSyncState("error");
                throw error;
            });
        }

        function refreshActiveThread() {
            if (!state.activeType || !state.activeTarget) {
                refreshOverview();
                return;
            }

            var newestId = getLoadedNewestId();
            loadThread(state.activeType, state.activeTarget, {
                mode: newestId ? "append" : "replace",
                afterId: newestId,
                scrollToBottom: newestId ? isFeedNearBottom() : true
            }).catch(function () {
                return;
            });
        }

        function refreshOverview() {
            if (document.hidden) {
                return;
            }

            if (state.chatOpen && state.currentView === "thread" && state.activeType && state.activeTarget) {
                refreshActiveThread();
                return;
            }

            setSyncState("syncing");
            fetchJson(root.dataset.bootstrapUrl).then(function (payload) {
                syncOverview(payload.overview);
                setSyncState("synced");
            }).catch(function () {
                setSyncState("error");
                return;
            });
        }

        function openConversation(type, target) {
            var sameThread = state.activeType === type && state.activeTarget === target;
            setChatOpen(true, { skipRefresh: true });
            state.currentView = "thread";
            syncOpenState();
            if (!sameThread) {
                showThreadLoading("Loading conversation...");
            }
            return loadThread(type, target, {
                mode: "replace",
                scrollToBottom: true
            }).then(function (payload) {
                setView("thread");
                if (!isMobileLayout() && refs.composeInput) {
                    refs.composeInput.focus();
                }
                return payload;
            });
        }

        function openDirectConversation(username) {
            if (!username) {
                return Promise.resolve();
            }
            return openConversation("direct", username);
        }

        function loadOlderMessages() {
            if (state.loadingOlder || !state.activeThread || !state.threadMeta || !state.threadMeta.has_more_before) {
                return;
            }

            var oldestId = getLoadedOldestId();
            if (!oldestId) {
                return;
            }

            state.loadingOlder = true;
            updateThreadTools();
            loadThread(state.activeType, state.activeTarget, {
                mode: "prepend",
                beforeId: oldestId,
                scrollToBottom: false
            }).finally(function () {
                state.loadingOlder = false;
                updateThreadTools();
            });
        }

        function findMessageById(messageId) {
            var numericId = Number(messageId);
            return state.threadMessages.find(function (item) {
                return Number(item.id) === numericId;
            }) || null;
        }

        function refreshCurrentThread(options) {
            if (!state.activeType || !state.activeTarget) {
                return Promise.resolve();
            }
            return loadThread(state.activeType, state.activeTarget, Object.assign({
                mode: "replace",
                scrollToBottom: false
            }, options || {}));
        }

        function handleMessageEdit(messageId) {
            var message = findMessageById(messageId);
            if (!message || !message.can_edit) {
                return;
            }
            var nextBody = window.prompt("Edit message", message.body || "");
            if (nextBody === null) {
                return;
            }
            nextBody = String(nextBody || "").trim();
            if (!nextBody && !message.attachment) {
                setComposeStatus("Message body cannot be blank.", "error");
                return;
            }
            var formData = new FormData();
            formData.append("message_id", String(message.id));
            formData.append("body", nextBody);
            setSyncState("syncing");
            fetchJson(root.dataset.messageUpdateUrl, {
                method: "POST",
                body: formData
            }).then(function (payload) {
                syncOverview(payload.overview);
                return refreshCurrentThread();
            }).then(function () {
                setComposeStatus("Message updated.", "success");
                setSyncState("synced");
            }).catch(function (error) {
                setComposeStatus(error.message || "Unable to update the message.", "error");
                setSyncState("error");
            });
        }

        function handleMessageDelete(messageId) {
            var message = findMessageById(messageId);
            if (!message || !message.can_delete) {
                return;
            }
            if (!window.confirm("Delete this message?")) {
                return;
            }
            var formData = new FormData();
            formData.append("message_id", String(message.id));
            setSyncState("syncing");
            fetchJson(root.dataset.messageDeleteUrl, {
                method: "POST",
                body: formData
            }).then(function (payload) {
                syncOverview(payload.overview);
                return refreshCurrentThread();
            }).then(function () {
                setComposeStatus("Message deleted.", "success");
                setSyncState("synced");
            }).catch(function (error) {
                setComposeStatus(error.message || "Unable to delete the message.", "error");
                setSyncState("error");
            });
        }

        function setSending(isSending) {
            state.sending = !!isSending;
            if (refs.compose) {
                refs.compose.classList.toggle("is-sending", state.sending);
            }
            updateComposerAvailability();
            syncComposerState();
        }

        function handleLayoutChange() {
            syncAppShellLayout();
            syncOpenState();
            autoResizeComposer();
            syncComposerState();
            if (state.activeThread) {
                applyThreadHeader(state.activeThread);
            }
        }

        if (refs.chatTrigger) {
            refs.chatTrigger.addEventListener("click", function (event) {
                event.stopPropagation();
                setChatOpen(!state.chatOpen);
            });
        }

        refs.filterButtons.forEach(function (button) {
            button.addEventListener("click", function () {
                state.filterMode = button.dataset.chatFilter || "all";
                refs.filterButtons.forEach(function (item) {
                    item.classList.toggle("is-active", item === button);
                });
                renderUnifiedList();
            });
        });

        if (refs.chatSearch) {
            refs.chatSearch.addEventListener("input", function () {
                state.searchTerm = normalizeSearch(refs.chatSearch.value);
                renderUnifiedList();
            });
        }

        if (refs.back) {
            refs.back.addEventListener("click", function () {
                setView("list");
                if (refs.chatSearch) {
                    refs.chatSearch.focus();
                }
            });
        }

        if (refs.refresh) {
            refs.refresh.addEventListener("click", function () {
                if (state.activeType && state.activeTarget) {
                    loadThread(state.activeType, state.activeTarget, {
                        mode: "replace",
                        scrollToBottom: false
                    }).catch(function () {
                        return;
                    });
                    return;
                }
                refreshOverview();
            });
        }

        if (refs.editToggle) {
            refs.editToggle.addEventListener("click", function () {
                setSettingsOpen(!state.settingsOpen);
            });
        }

        if (refs.editCancel) {
            refs.editCancel.addEventListener("click", function () {
                setSettingsOpen(false);
            });
        }

        if (refs.channelForm) {
            refs.channelForm.addEventListener("submit", function (event) {
                event.preventDefault();
                var formData = new FormData(refs.channelForm);
                setSyncState("syncing");
                fetchJson(root.dataset.channelUpdateUrl, {
                    method: "POST",
                    body: formData
                }).then(function (payload) {
                    setSettingsOpen(false);
                    syncOverview(payload.overview);
                    if (state.activeType && state.activeTarget) {
                        return loadThread(state.activeType, state.activeTarget, {
                            mode: "replace",
                            scrollToBottom: false
                        });
                    }
                    setSyncState("synced");
                    return null;
                }).catch(function () {
                    setSyncState("error");
                    return;
                });
            });
        }

        if (refs.fileInput) {
            refs.fileInput.addEventListener("change", function () {
                var file = refs.fileInput.files && refs.fileInput.files.length ? refs.fileInput.files[0] : null;
                if (file && file.size > maxAttachmentSizeBytes) {
                    refs.fileInput.value = "";
                    updateFilePreview();
                    setComposeStatus("Attachments must be 15 MB or smaller.", "error");
                    return;
                }
                updateFilePreview();
                setComposeStatus(file ? "Attachment ready to send." : "");
            });
        }

        if (refs.fileClear) {
            refs.fileClear.addEventListener("click", function () {
                if (refs.fileInput) {
                    refs.fileInput.value = "";
                }
                updateFilePreview();
                if (!String((refs.composeInput && refs.composeInput.value) || "").trim()) {
                    setComposeStatus("");
                }
            });
        }

        if (refs.composeInput) {
            refs.composeInput.addEventListener("input", function () {
                saveCurrentDraft();
                autoResizeComposer();
                syncComposerState();
                if (refs.composeStatus && refs.composeStatus.classList.contains("is-error")) {
                    setComposeStatus("");
                }
            });

            refs.composeInput.addEventListener("keydown", function (event) {
                if (isMobileLayout()) {
                    return;
                }
                if (event.key === "Enter" && !event.shiftKey && !event.ctrlKey && !event.metaKey && !event.altKey) {
                    event.preventDefault();
                    if (refs.compose && typeof refs.compose.requestSubmit === "function") {
                        refs.compose.requestSubmit();
                    } else if (refs.compose) {
                        refs.compose.dispatchEvent(new Event("submit", {
                            bubbles: true,
                            cancelable: true
                        }));
                    }
                }
            });
        }

        if (refs.compose) {
            refs.compose.addEventListener("focusin", function () {
                syncComposerState();
            });

            refs.compose.addEventListener("focusout", function () {
                window.setTimeout(syncComposerState, 0);
            });

            refs.compose.addEventListener("submit", function (event) {
                event.preventDefault();
                if (!refs.composeType || !refs.composeTarget || !refs.composeType.value || !refs.composeTarget.value) {
                    setComposeStatus("Select a conversation first.", "error");
                    return;
                }
                if (state.sending) {
                    return;
                }

                var hasMessage = !!String((refs.composeInput && refs.composeInput.value) || "").trim();
                var hasFile = !!(refs.fileInput && refs.fileInput.files && refs.fileInput.files.length);
                if (!hasMessage && !hasFile) {
                    setComposeStatus("Enter a message or attach a file.", "error");
                    return;
                }

                var formData = new FormData(refs.compose);
                setSending(true);
                setComposeStatus("Sending...", "success");
                setSyncState("syncing");

                fetchJson(root.dataset.sendUrl, {
                    method: "POST",
                    body: formData
                }).then(function (payload) {
                    clearComposer();
                    syncOverview(payload.overview);
                    applyThreadPayload(payload, "append");
                    setView("thread");
                    scrollFeedToBottom();
                    state.unseenCount = 0;
                    setComposeStatus("Message sent.", "success");
                    setSyncState("synced");
                    if (!isMobileLayout() && refs.composeInput) {
                        refs.composeInput.focus();
                    }
                }).catch(function (error) {
                    setComposeStatus(error.message || "Unable to send message or attachment.", "error");
                    setSyncState("error");
                }).then(function () {
                    setSending(false);
                }, function () {
                    setSending(false);
                });
            });
        }

        if (refs.feed) {
            refs.feed.addEventListener("scroll", function () {
                syncJumpLatestVisibility();
            });
        }

        if (refs.loadOlder) {
            refs.loadOlder.addEventListener("click", function () {
                loadOlderMessages();
            });
        }

        if (refs.jumpLatest) {
            refs.jumpLatest.addEventListener("click", function () {
                scrollFeedToBottom();
                state.unseenCount = 0;
                syncJumpLatestVisibility();
            });
        }

        Array.prototype.slice.call(document.querySelectorAll("[data-profile-chat-search-input]")).forEach(function (input) {
            input.addEventListener("input", function () {
                renderProfileSearchPanels();
            });
        });

        document.addEventListener("keydown", function (event) {
            if (event.key === "Escape" && state.chatOpen) {
                setChatOpen(false);
            }
        });

        document.addEventListener("click", function (event) {
            var openTrigger = event.target.closest("[data-chat-open-user]");
            if (openTrigger) {
                event.preventDefault();
                openDirectConversation(openTrigger.getAttribute("data-chat-open-user")).catch(function (error) {
                    setComposeStatus(error.message, "error");
                });
                return;
            }

            var favoriteTrigger = event.target.closest("[data-chat-favorite-toggle]");
            if (favoriteTrigger) {
                event.preventDefault();
                var targetUsername = favoriteTrigger.getAttribute("data-chat-favorite-toggle");
                var shouldFavorite = favoriteTrigger.getAttribute("data-chat-favorite-active") !== "true";
                toggleFavorite(targetUsername, shouldFavorite, favoriteTrigger).catch(function () {
                    return;
                });
                return;
            }

            var editTrigger = event.target.closest("[data-chat-edit-message]");
            if (editTrigger) {
                event.preventDefault();
                handleMessageEdit(editTrigger.getAttribute("data-chat-edit-message"));
                return;
            }

            var deleteTrigger = event.target.closest("[data-chat-delete-message]");
            if (deleteTrigger) {
                event.preventDefault();
                handleMessageDelete(deleteTrigger.getAttribute("data-chat-delete-message"));
            }
        });

        document.addEventListener("visibilitychange", function () {
            if (!document.hidden) {
                refreshOverview();
            }
        });

        if (mobileQuery.addEventListener) {
            mobileQuery.addEventListener("change", handleLayoutChange);
        } else if (mobileQuery.addListener) {
            mobileQuery.addListener(handleLayoutChange);
        }

        fetchJson(root.dataset.bootstrapUrl).then(function (payload) {
            syncOverview(payload.overview);
            applyThreadHeader(null);
            updateComposerAvailability();
            autoResizeComposer();
            setSyncState("synced");
        }).catch(function () {
            applyThreadHeader(null);
            updateComposerAvailability();
            setSyncState("error");
            return;
        });

        autoResizeComposer();
        syncComposerState();
        syncOpenState();
        renderSyncStatus();
        state.pollHandle = window.setInterval(refreshOverview, Number(root.dataset.pollMs || 15000));
    }

    function init() {
        Array.prototype.slice.call(document.querySelectorAll("[data-chat-widget]")).forEach(initChatWidget);
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init, { once: true });
    } else {
        init();
    }
})();
