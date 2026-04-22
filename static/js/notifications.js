// 学生端通知红点轮询（60 秒一次；页面隐藏时暂停）
(function () {
    var ENDPOINT = '/notifications/unread_count';
    var INTERVAL_MS = 60 * 1000;

    function refresh() {
        if (document.hidden) return;
        fetch(ENDPOINT, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data) return;
                var meTab = document.querySelector('.bottom-tabbar a[href$="/me"]');
                if (!meTab) return;
                meTab.querySelectorAll('.dot-badge').forEach(function (b) { b.remove(); });
                if (data.count && data.count > 0) {
                    var el = document.createElement('em');
                    el.className = 'dot-badge';
                    el.textContent = data.count;
                    meTab.appendChild(el);
                }
            })
            .catch(function () {});
    }
    setInterval(refresh, INTERVAL_MS);
    document.addEventListener('visibilitychange', function () {
        if (!document.hidden) refresh();
    });
})();
