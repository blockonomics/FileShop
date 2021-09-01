import {apiendpoints, static_urls } from "../../apiendpoints";

export default {
    sidebar_visible: true,

    apiendpoints,
    static_urls,

    common_toast_options: {
        autoHideDelay: 5000,
        appendToast: false,
        variant: 'success',
        toaster: 'b-toaster-bottom-center'
    }
}