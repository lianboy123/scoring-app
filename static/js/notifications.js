// 学生端通知红点轮询（5 分钟一次）
(function () {
    var ENDPOINT = '/notifications/unread_count';
    function refresh() {
        fetch(ENDPOINT, { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (data) {
                if (!data) return;
                var badges = document.querySelectorAll('.bottom-tabbar a .dot-badge');
                var meTab = document.querySelector('.bottom-tabbar a[href$="/me"]');
                if (!meTab) return;
                badges.forEach(function (b) { b.remove(); });
                if (data.count && data.count > 0) {
                    var el = document.createElement('em');
                    el.className = 'dot-badge';
                    el.textContent = data.count;
                    meTab.appendChild(el);
                }
            })
            .catch(function () {});
    }
    setInterval(refresh, 5 * 60 * 1000);
})();
