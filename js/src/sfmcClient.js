const sfmc = require("sfmc");

async function connect() {

    const auth = await sfmc.accessToken.getAccessToken();

    const stompClient = await sfmc.stompConnect.connect(auth.token);

    return {
        auth,
        stompClient
    };
}

async function getGliderId(token, gliderName) {

    const result = await sfmc.glider.getGliderDetails(
        token,
        gliderName
    );

    return result.data.id;
}

function subscribeToConnectionEvents(
    stompClient,
    gliderId,
    callback
) {

    sfmc.glider.subscribeForConnectionEvents(
        stompClient,
        gliderId,
        callback
    );
}

module.exports = {
    connect,
    getGliderId,
    subscribeToConnectionEvents
};
