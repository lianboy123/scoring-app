// 极简 Toast：基于 Bootstrap toast，自动从 flash messages 渲染
(function () {
    function showToast(message, category) {
        var container = document.getElementById('toastContainer');
        if (!container) return;
        var bg = ({
            success: 'text-bg-success',
            danger: 'text-bg-danger',
            warning: 'text-bg-warning',
            info: 'text-bg-info'
        })[category] || 'text-bg-secondary';

        var el = document.createElement('div');
        el.className = 'toast ' + bg + ' border-0';
        el.setAttribute('role', 'status');
        el.setAttribute('aria-live', 'polite');
        el.innerHTML =
            '<div class="d-flex">' +
                '<div class="toast-body">' + message + '</div>' +
                '<button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>' +
            '</div>';
        container.appendChild(el);
        var toast = bootstrap.Toast.getOrCreateInstance(el, { delay: 3500 });
        toast.show();
        el.addEventListener('hidden.bs.toast', function () { el.remove(); });
    }

    window.appToast = showToast;

    document.addEventListener('DOMContentLoaded', function () {
        var box = document.getElementById('flashedMessages');
        if (!box) return;
        box.querySelectorAll('div[data-msg]').forEach(function (n) {
            showToast(n.dataset.msg, n.dataset.cat);
        });
    });
})();
