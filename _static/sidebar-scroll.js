(function () {
    function resetSidebarScroll() {
        var sidebar = document.querySelector(".wy-nav-side");

        if (!sidebar) {
            return;
        }

        sidebar.scrollTop = 0;
    }

    window.addEventListener("load", function () {
        resetSidebarScroll();
        window.setTimeout(resetSidebarScroll, 150);
    });
})();
